package gm.conduit.mobs;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.api.AnimatedEntityHolder;
import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.holder.entity.living.LivingEntityHolder;
import de.tomalbrc.bil.core.model.Animation;
import de.tomalbrc.bil.core.model.Model;
import eu.pb4.polymer.virtualentity.api.attachment.EntityAttachment;
import eu.pb4.polymer.virtualentity.api.elements.TextDisplayElement;
import gm.conduit.api.MobBehavior;
import gm.conduit.modules.ServerModuleHost;
import de.tomalbrc.bil.core.holder.wrapper.Bone;
import de.tomalbrc.bil.core.holder.wrapper.ItemBone;
import eu.pb4.polymer.virtualentity.api.elements.DisplayElement;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.sounds.SoundSource;
import net.minecraft.util.Brightness;
import net.minecraft.util.Mth;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Display;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityDimensions;
import net.minecraft.world.entity.EntityEvent;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.ai.control.FlyingMoveControl;
import net.minecraft.world.entity.ai.control.MoveControl;
import net.minecraft.world.entity.ai.navigation.FlyingPathNavigation;
import net.minecraft.world.entity.ai.util.DefaultRandomPos;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.PathfinderMob;
import net.minecraft.world.entity.Pose;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.entity.ai.goal.AvoidEntityGoal;
import net.minecraft.world.entity.ai.goal.FloatGoal;
import net.minecraft.world.entity.ai.goal.LookAtPlayerGoal;
import net.minecraft.world.entity.ai.goal.MeleeAttackGoal;
import net.minecraft.world.entity.ai.goal.PanicGoal;
import net.minecraft.world.entity.ai.goal.RandomLookAroundGoal;
import net.minecraft.world.entity.ai.goal.WaterAvoidingRandomFlyingGoal;
import net.minecraft.world.entity.ai.goal.WaterAvoidingRandomStrollGoal;
import net.minecraft.world.entity.ai.goal.target.HurtByTargetGoal;
import net.minecraft.world.entity.ai.goal.target.NearestAttackableTargetGoal;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;

import java.util.UUID;
import java.util.function.Consumer;

/**
 * A creature with no fixed identity. Its type is one of a fixed pool registered at boot, and everything else
 * comes from the current release: looks, size, stats, behaviour, so a new mob needs no restart. A slot with
 * nothing bound removes itself rather than standing around invisible.
 */
public final class SlotMob extends PathfinderMob implements AnimatedEntity {
	private static final String IDLE = "idle";
	private static final String WALK = "walk";
	private static final String FLY = "fly";
	/** How long a mob keeps trying to get somewhere before giving up, however far that is, and how often it looks for a way again. */
	private static final int WALK_GIVES_UP_TICKS = 2400;
	private static final int WALK_REPLAN_TICKS = 20;
	private static final int STUCK_TRIES = 6;
	private static final double ARRIVED_WITHIN = 1.5;
	private static final String HURT = "hurt";
	private static final String DEATH = "death";
	private static final int NORMAL_DEATH_TICKS = 20;
	private static final int LONGEST_DEATH_TICKS = 100;
	private static final String STAY = "stay";
	private static final String WANDER = "wander";
	private static final int THINKING_TICKS = 120;
	private static final int STAY_TICKS = 400;
	private static final int ACTION_TICKS = 1200;
	private static final double FOLLOW_DISTANCE = 3.0;
	private static final int BUBBLE_WIDTH = 160;
	private static final double BUBBLE_GAP = 0.4;
	private static final int BUBBLE_MIN_TICKS = 60;
	private static final int BUBBLE_TICKS_PER_LETTER = 2;
	private static final int MOVE_WAIT_TICKS = 80;
	/** What a model is drawn with when nothing's tinting it, which is white. */
	private static final int NO_TINT = 0xFFFFFF;
	private static final float BABY_SIZE = LivingEntity.DEFAULT_BABY_SCALE;
	private static final int TICKS_PER_SECOND = 20;

	private LivingEntityHolder<SlotMob> holder;
	private MobDefinition applied;
	/** The animation being held still for a photograph, if any. Nothing else plays while it's set. */
	private String posed;
	private int posedFrame;
	private int animatedDeathTicks;
	/** What its mind decided to do, whose sake it's for, and until when. Null for nothing in particular. */
	private String mindAction;
	private UUID mindPlayer;
	private BlockPos mindPlace;
	private int mindUntil;
	private TextDisplayElement bubble;
	private int bubbleUntil;
	/** When to choose a fight move by itself, if no decision has arrived by then. */
	private int moveDeadline;
	private int tint = NO_TINT;
	/** How long until it's grown, in ticks. It's only a baby while this isn't 0, and if it's below 0 it stays one. */
	private int growsUpIn;
	/** Where a module has sent it, with what to do once it's there, and who asked. Not saved, because that's code that may not be there next time. */
	private BlockPos walkingTo;
	private double walkSpeed;
	private Consumer<Boolean> walkDone;
	private MobBehavior walkOwner;
	private int walkUntil;
	private int walkNextLook;
	private int walkFailures;
	private boolean flies;
	/** What modules have done to its parts, by part, kept here so it comes back with the world. */
	private CompoundTag parts = new CompoundTag();

	public SlotMob(EntityType<? extends PathfinderMob> type, Level level) {
		super(type, level);
		if (!level.isClientSide()) {
			MobDefinition definition = SlotMobs.definition(type);
			if (definition != null) {
				apply(definition);
				setHealth(getMaxHealth());
			}
		}
	}

	private String slotId() {
		return BuiltInRegistries.ENTITY_TYPE.getKey(getType()).getPath();
	}

	public Animator animator() {
		return this.holder == null ? null : this.holder.getAnimator();
	}

	private void apply(MobDefinition definition) {
		this.applied = definition;
		getAttribute(Attributes.MAX_HEALTH).setBaseValue(definition.health());
		getAttribute(Attributes.ATTACK_DAMAGE).setBaseValue(definition.damage());
		getAttribute(Attributes.MOVEMENT_SPEED).setBaseValue(definition.speed());
		getAttribute(Attributes.FOLLOW_RANGE).setBaseValue(definition.followRange());
		getAttribute(Attributes.ARMOR).setBaseValue(definition.armor());
		getAttribute(Attributes.KNOCKBACK_RESISTANCE).setBaseValue(definition.knockbackResistance());
		getAttribute(Attributes.FLYING_SPEED).setBaseValue(definition.speed());
		setFlies(definition.flying());
		refreshDimensions();
		if (this.holder != null) {
			this.holder.destroy();
			this.holder = null;
		}
		var model = SlotMobs.model(definition.model());
		if (model != null) {
			this.holder = new LivingEntityHolder<>(this, model);
			EntityAttachment.ofTicking(this.holder, this);
			applyLook();
		}
		this.goalSelector.removeAllGoals(goal -> true);
		this.targetSelector.removeAllGoals(goal -> true);
		installGoals(definition);
	}

	@Override
	protected void registerGoals() {
		// Goals depend on the definition, which isn't known this early. See apply().
	}

	private void installGoals(MobDefinition definition) {
		this.goalSelector.addGoal(0, new FloatGoal(this));
		this.goalSelector.addGoal(1, new WalkGoal(this));
		if (definition.mind() != null) {
			this.goalSelector.addGoal(1, new MindGoal(this));
		}
		switch (definition.behaviour()) {
			case "hostile" -> {
				this.goalSelector.addGoal(2, new MeleeAttackGoal(this, 1.0, false));
				this.targetSelector.addGoal(1, new HurtByTargetGoal(this));
				this.targetSelector.addGoal(2, new NearestAttackableTargetGoal<>(this, Player.class, true));
			}
			case "neutral" -> {
				this.goalSelector.addGoal(2, new MeleeAttackGoal(this, 1.0, false));
				this.targetSelector.addGoal(1, new HurtByTargetGoal(this));
			}
			case "skittish" -> {
				this.goalSelector.addGoal(1, new AvoidEntityGoal<>(this, Player.class, 8.0F, 1.0, 1.4));
				this.goalSelector.addGoal(2, new PanicGoal(this, 1.4));
			}
			default -> this.goalSelector.addGoal(2, new PanicGoal(this, 1.4));
		}
		this.goalSelector.addGoal(5, definition.flying() ? new WaterAvoidingRandomFlyingGoal(this, 0.8) : new WaterAvoidingRandomStrollGoal(this, 0.8));
		this.goalSelector.addGoal(6, new LookAtPlayerGoal(this, Player.class, 8.0F));
		this.goalSelector.addGoal(7, new RandomLookAroundGoal(this));
	}

	@Override
	public void tick() {
		super.tick();
		if (level().isClientSide()) {
			return;
		}
		MobDefinition current = SlotMobs.definition(getType());
		if (current == null) {
			discard();
			return;
		}
		// A release may have changed this mob while it was alive.
		if (current != this.applied && !current.equals(this.applied)) {
			apply(current);
		}
		// The game only works this out on clients now, and it's what says whether to play its walk.
		calculateEntityAnimation(this.flies);
		if (this.posed != null) {
			holdPose();
		} else if (this.tickCount % 2 == 0) {
			updateAnimation();
		}
		growUp();
		tickMind();
		MobBehavior behavior = ServerModuleHost.instance().mobBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.tick(this));
		}
	}

	/** Flying is how it's steered, not just that it stays up, so this swaps what does the steering. */
	private void setFlies(boolean flying) {
		if (flying == this.flies) {
			return;
		}
		this.flies = flying;
		getNavigation().stop();
		if (flying) {
			this.moveControl = new FlyingMoveControl<>(this, 20, true);
			FlyingPathNavigation navigation = new FlyingPathNavigation(this, level());
			navigation.setCanOpenDoors(false);
			navigation.setCanFloat(true);
			this.navigation = navigation;
		} else {
			this.moveControl = new MoveControl(this);
			this.navigation = createNavigation(level());
		}
	}

	public boolean isFlying() {
		return this.flies;
	}

	/** It's asked rather than set, because loading one or summoning one with any data at all overwrites what's set. */
	@Override
	public boolean isNoGravity() {
		return this.flies || super.isNoGravity();
	}

	/** Lets it stay as steady going up or down as it does going along, as a bee does. */
	@Override
	protected boolean omnidirectionalAirMover() {
		return this.flies;
	}

	@Override
	public void travel(Vec3 input) {
		if (this.flies) {
			travelFlying(input, getSpeed());
		} else {
			super.travel(input);
		}
	}

	@Override
	protected void checkFallDamage(double ya, boolean onGround, BlockState onState, BlockPos pos) {
		if (!this.flies) {
			super.checkFallDamage(ya, onGround, onState, pos);
		}
	}

	/**
	 * Goes to a block, over whatever its usual wandering would have it do, and says how that went: true once it's there, or false if it can't get there or
	 * gives up after 2 minutes. Its speed is a multiple of its usual one. Anything it's already been told to walk to is forgotten, and hears false. A restart,
	 * or its module being replaced, forgets it too, without a word, because the code to run wouldn't be there.
	 */
	public void walkTo(BlockPos place, double speed, Consumer<Boolean> done) {
		finishWalk(false);
		this.walkingTo = place;
		this.walkSpeed = speed;
		this.walkDone = done;
		this.walkOwner = ServerModuleHost.instance().mobBehavior(slotId());
		this.walkUntil = this.tickCount + WALK_GIVES_UP_TICKS;
		this.walkNextLook = this.tickCount;
		this.walkFailures = 0;
		getNavigation().stop();
	}

	public boolean isWalking() {
		return this.walkingTo != null;
	}

	/** Stops it walking anywhere, which it hears as not having got there. */
	public void stopWalking() {
		finishWalk(false);
		getNavigation().stop();
	}

	/** Only WalkGoal calls this, so a mob with its AI turned off just stands still. */
	void tickWalk() {
		if (this.walkingTo == null) {
			return;
		}
		if (ServerModuleHost.instance().mobBehavior(slotId()) != this.walkOwner) {
			this.walkingTo = null;
			this.walkDone = null;
			return;
		}
		if (position().closerThan(Vec3.atBottomCenterOf(this.walkingTo), ARRIVED_WITHIN)) {
			getNavigation().stop();
			finishWalk(true);
			return;
		}
		if (this.tickCount >= this.walkUntil) {
			finishWalk(false);
		} else if (this.tickCount >= this.walkNextLook) {
			this.walkNextLook = this.tickCount + WALK_REPLAN_TICKS;
			boolean found = getNavigation().moveTo(this.walkingTo.getX() + 0.5, this.walkingTo.getY(), this.walkingTo.getZ() + 0.5, this.walkSpeed);
			this.walkFailures = found ? 0 : this.walkFailures + 1;
			if (this.walkFailures >= STUCK_TRIES) {
				finishWalk(false);
			}
		}
	}

	private void finishWalk(boolean arrived) {
		Consumer<Boolean> done = this.walkDone;
		this.walkingTo = null;
		this.walkDone = null;
		if (done != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> done.accept(arrived));
		}
	}

	/** Colours one part of its model, by its name there, as {@link #setTint} does for all of it. Returns false if it has no such part. */
	public boolean tintPart(String part, int rgb) {
		Bone<?> bone = this.holder == null ? null : this.holder.getBone(part);
		if (bone == null) {
			return false;
		}
		if (bone instanceof ItemBone item) {
			item.updateColor(rgb);
		}
		CompoundTag tag = this.parts.getCompoundOrEmpty(part);
		tag.putInt("tint", rgb);
		this.parts.put(part, tag);
		return true;
	}

	/** Makes one part of its model give its own light, from 0 to 15, whatever's around it. Returns false if it has no such part. */
	public boolean glowPart(String part, int level) {
		Bone<?> bone = this.holder == null ? null : this.holder.getBone(part);
		if (bone == null) {
			return false;
		}
		int glow = Mth.clamp(level, 0, 15);
		if (bone.element() instanceof DisplayElement element) {
			element.setBrightness(new Brightness(glow, glow));
		}
		CompoundTag tag = this.parts.getCompoundOrEmpty(part);
		tag.putInt("glow", glow);
		this.parts.put(part, tag);
		return true;
	}

	/** What its definition says should glow, then what's been done to this one. */
	private void applyParts() {
		if (this.holder == null || this.applied == null) {
			return;
		}
		for (String part : this.applied.glowing()) {
			Bone<?> bone = this.holder.getBone(part);
			if (bone != null && bone.element() instanceof DisplayElement element) {
				element.setBrightness(Brightness.FULL_BRIGHT);
			}
		}
		for (String part : this.parts.keySet()) {
			CompoundTag tag = this.parts.getCompoundOrEmpty(part);
			Bone<?> bone = this.holder.getBone(part);
			if (bone instanceof ItemBone item && tag.contains("tint")) {
				item.updateColor(tag.getIntOr("tint", NO_TINT));
			}
			if (bone != null && bone.element() instanceof DisplayElement element && tag.contains("glow")) {
				element.setBrightness(new Brightness(tag.getIntOr("glow", 0), tag.getIntOr("glow", 0)));
			}
		}
	}

	/** Colours this one's model, for a mob whose kinds shouldn't each need an entry of their own. Keep it in its own saved data if it has to be chosen again. */
	public void setTint(int rgb) {
		this.tint = rgb;
		applyLook();
	}

	public int tint() {
		return this.tint;
	}

	/** Makes this one a baby, half the size, which grows up by itself after this many seconds. With 0 or less it stays one. */
	public void makeBaby(int growsUpInSeconds) {
		this.growsUpIn = growsUpInSeconds > 0 ? growsUpInSeconds * TICKS_PER_SECOND : -1;
		applySize();
	}

	@Override
	public boolean isBaby() {
		return this.growsUpIn != 0;
	}

	@Override
	public void setBaby(boolean baby) {
		if (baby != isBaby()) {
			if (baby) {
				makeBaby(0);
			} else {
				this.growsUpIn = 0;
				applySize();
			}
		}
	}

	private void growUp() {
		if (this.growsUpIn > 0 && --this.growsUpIn == 0) {
			applySize();
		}
	}

	/** Its scale is the one thing its hitbox and its model both go by, and it's saved with it. */
	private void applySize() {
		getAttribute(Attributes.SCALE).setBaseValue(isBaby() ? BABY_SIZE : 1.0F);
		refreshDimensions();
	}

	private void applyLook() {
		if (this.holder != null) {
			this.holder.setColor(this.tint);
			applyParts();
		}
	}

	@Override
	protected void addAdditionalSaveData(ValueOutput output) {
		super.addAdditionalSaveData(output);
		output.putInt("tint", this.tint);
		output.putInt("grows_up_in", this.growsUpIn);
		if (!this.parts.isEmpty()) {
			output.store("parts", CompoundTag.CODEC, this.parts);
		}
	}

	@Override
	protected void readAdditionalSaveData(ValueInput input) {
		super.readAdditionalSaveData(input);
		this.tint = input.getIntOr("tint", NO_TINT);
		this.growsUpIn = input.getIntOr("grows_up_in", 0);
		this.parts = input.read("parts", CompoundTag.CODEC).orElseGet(CompoundTag::new);
		applyLook();
	}

	private void updateAnimation() {
		Animator animator = animator();
		if (animator == null || this.posed != null || isDeadOrDying()) {
			return;
		}
		String moving = this.flies && animation(FLY) != null ? FLY : WALK;
		if (this.walkAnimation.isMoving() && this.walkAnimation.speed() > 0.02F) {
			animator.pauseAnimation(IDLE);
			animator.playAnimation(moving, 5);
		} else {
			animator.pauseAnimation(moving);
			animator.playAnimation(IDLE, 1, true);
		}
	}

	// Its mind ------------------------------------------------------------------------------------------

	public Mind mind() {
		return this.applied == null ? null : this.applied.mind();
	}

	String displayName() {
		return this.applied == null || this.applied.display().isEmpty() ? getType().getDescription().getString() : this.applied.display();
	}

	boolean isPeaceful() {
		return this.applied != null && (this.applied.behaviour().equals("passive") || this.applied.behaviour().equals("skittish"));
	}

	boolean isHostile() {
		return this.applied != null && this.applied.behaviour().equals("hostile");
	}

	@Override
	protected InteractionResult mobInteract(Player player, InteractionHand hand) {
		MobBehavior behavior = ServerModuleHost.instance().mobBehavior(slotId());
		if (behavior != null && !level().isClientSide()) {
			InteractionResult result = ServerModuleHost.instance().guarded(slotId(), InteractionResult.PASS, () -> behavior.interact(this, player, hand));
			if (result != InteractionResult.PASS) {
				return result;
			}
		}
		if (mind() != null && player instanceof ServerPlayer serverPlayer) {
			return Minds.onUse(this, serverPlayer, hand);
		}
		return super.mobInteract(player, hand);
	}

	/** Turns to whoever spoke straight away, so the short wait for a decision looks like it's considering them. */
	void thinkAbout(ServerPlayer player) {
		if (this.mindAction == null) {
			startAction(STAY, player, null);
			this.mindUntil = this.tickCount + THINKING_TICKS;
		}
	}

	void startAction(String action, ServerPlayer player, BlockPos place) {
		this.mindAction = WANDER.equals(action) ? null : action;
		this.mindPlayer = player.getUUID();
		this.mindPlace = place;
		this.mindUntil = this.tickCount + (STAY.equals(action) ? STAY_TICKS : ACTION_TICKS);
		getNavigation().stop();
	}

	boolean hasMindAction() {
		return this.mindAction != null;
	}

	/** Only MindGoal calls this, so a mob with its AI turned off just stands still. */
	void tickMindAction() {
		String action = this.mindAction;
		Player player = this.mindPlayer == null ? null : level().getPlayerByUUID(this.mindPlayer);
		// It can be told to stop between a goal's check and its tick, and a mob's choice must never be able to stop the server.
		if (action == null || player == null || this.tickCount >= this.mindUntil) {
			this.mindAction = null;
			return;
		}
		switch (action) {
			case "follow" -> {
				getLookControl().setLookAt(player);
				if (distanceTo(player) > FOLLOW_DISTANCE && this.tickCount % 10 == 0) {
					getNavigation().moveTo(player, 1.1);
				}
			}
			case "flee" -> {
				if (this.tickCount % 20 == 0) {
					Vec3 away = DefaultRandomPos.getPosAway(this, 16, 7, player.position());
					if (away != null) {
						getNavigation().moveTo(away.x, away.y, away.z, 1.3);
					}
				}
			}
			case "lead" -> {
				if (this.mindPlace != null && this.tickCount % 20 == 0) {
					getNavigation().moveTo(this.mindPlace.getX() + 0.5, this.mindPlace.getY(), this.mindPlace.getZ() + 0.5, 1.0);
				}
				if (this.mindPlace == null || blockPosition().closerThan(this.mindPlace, 3)) {
					getLookControl().setLookAt(player);
				}
			}
			default -> getLookControl().setLookAt(player);
		}
	}

	void say(String text) {
		Minds.speakAround(this, text);
		if (this.holder == null) {
			return;
		}
		clearBubble();
		this.bubble = new TextDisplayElement(Component.literal(text));
		this.bubble.setBillboardMode(Display.BillboardConstraints.CENTER);
		this.bubble.setLineWidth(BUBBLE_WIDTH);
		this.bubble.setOffset(new Vec3(0, getBbHeight() + BUBBLE_GAP, 0));
		this.holder.addElement(this.bubble);
		this.bubbleUntil = this.tickCount + BUBBLE_MIN_TICKS + text.length() * BUBBLE_TICKS_PER_LETTER;
	}

	private void clearBubble() {
		if (this.bubble != null && this.holder != null) {
			this.holder.removeElement(this.bubble);
		}
		this.bubble = null;
	}

	boolean playIfAllowed(String name) {
		Animator animator = animator();
		if (animator == null || mind() == null || !mind().animations().contains(name) || animation(name) == null) {
			return false;
		}
		animator.playAnimation(name, 9, true);
		return true;
	}

	boolean soundIfAllowed(String name) {
		if (mind() == null || !mind().sounds().contains(name)) {
			return false;
		}
		Identifier id = Identifier.parse(name);
		level().playSound(null, getX(), getY(), getZ(), SoundEvent.createVariableRangeEvent(id), SoundSource.NEUTRAL, 1.0F, 1.0F);
		return true;
	}

	/** A fight move is the module's to carry out. All a mind does is choose when to use which. */
	boolean performMove(String name) {
		if (mind() == null || !mind().moves().contains(name)) {
			return false;
		}
		this.moveDeadline = 0;
		Animator animator = animator();
		if (animator != null && animation(name) != null) {
			animator.playAnimation(name, 12, true);
		}
		MobBehavior behavior = ServerModuleHost.instance().mobBehavior(slotId());
		LivingEntity target = getTarget();
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.move(this, name, target));
		}
		return true;
	}

	private void tickMind() {
		if (this.bubble != null && this.tickCount >= this.bubbleUntil) {
			clearBubble();
		}
		Mind mind = mind();
		if (mind == null || mind.moves().isEmpty() || !(getTarget() instanceof ServerPlayer target) || !target.isAlive()) {
			return;
		}
		// If nothing's decided in time, say because the agent's out of usage, a fight carries on with a random move.
		if (this.moveDeadline > 0 && this.tickCount >= this.moveDeadline) {
			performMove(mind.moves().get(getRandom().nextInt(mind.moves().size())));
		}
		if (this.tickCount % (mind.fightSeconds() * 20) == 0) {
			this.moveDeadline = this.tickCount + MOVE_WAIT_TICKS;
			Minds.onFight(this, target);
		}
	}

	private Animation animation(String name) {
		Model model = this.applied == null ? null : SlotMobs.model(this.applied.model());
		return model == null ? null : model.animations().get(name);
	}

	/**
	 * Holds one moment of an animation, so a test client can photograph exactly that moment, whatever the timing of its
	 * screenshots. Returns false if this mob has no such animation.
	 */
	public boolean pose(String name, float fraction) {
		Animator animator = animator();
		Animation animation = animation(name);
		if (animator == null || animation == null) {
			return false;
		}
		animator.stopAnimation(IDLE);
		animator.stopAnimation(WALK);
		animator.stopAnimation(FLY);
		if (this.posed != null) {
			animator.stopAnimation(this.posed);
		}
		this.posed = name;
		this.posedFrame = Mth.clamp((int) (fraction * animation.frames().length), 0, animation.frames().length - 1);
		holdPose();
		return true;
	}

	private void holdPose() {
		// A paused animation shows nothing at all, only the resting pose, so this one keeps playing and gets put back
		// at the same frame every tick.
		Animator animator = animator();
		if (animator != null) {
			animator.playAnimation(this.posed, 100);
			animator.setAnimationFrame(this.posed, this.posedFrame);
		}
	}

	@Override
	public boolean hurtServer(ServerLevel level, DamageSource source, float amount) {
		MobBehavior behavior = ServerModuleHost.instance().mobBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.hurt(this, source));
		}
		boolean hurt = super.hurtServer(level, source, amount);
		if (hurt && !isDeadOrDying() && animator() != null && animation(HURT) != null) {
			animator().playAnimation(HURT, 8, true);
		}
		if (hurt && mind() != null && source.getEntity() instanceof ServerPlayer attacker) {
			Minds.onHurt(this, attacker);
		}
		return hurt;
	}

	@Override
	public void die(DamageSource source) {
		super.die(source);
		if (animator() != null && animation(DEATH) != null) {
			animator().stopAnimation(IDLE);
			animator().stopAnimation(WALK);
			animator().stopAnimation(FLY);
			animator().playAnimation(DEATH, 20, true);
		}
	}

	/**
	 * A death animation gets to finish before the body goes. It counts by itself and leaves deathTime alone, because the
	 * model library tips anything with a deathTime over on its side, which would turn every fall into a sideways one.
	 */
	@Override
	protected void tickDeath() {
		Animation death = animation(DEATH);
		if (death == null) {
			super.tickDeath();
			return;
		}
		this.animatedDeathTicks++;
		if (this.animatedDeathTicks >= Mth.clamp(death.duration(), NORMAL_DEATH_TICKS, LONGEST_DEATH_TICKS) && !level().isClientSide() && !isRemoved()) {
			level().broadcastEntityEvent(this, EntityEvent.POOF);
			remove(RemovalReason.KILLED);
		}
	}

	private SoundEvent ownSound(String kind, SoundEvent otherwise) {
		SoundEvent own = this.applied == null ? null : this.applied.sounds().get(kind);
		return own != null ? own : otherwise;
	}

	@Override
	protected SoundEvent getAmbientSound() {
		return ownSound(IDLE, super.getAmbientSound());
	}

	@Override
	protected SoundEvent getHurtSound(DamageSource source) {
		return ownSound(HURT, super.getHurtSound(source));
	}

	@Override
	protected SoundEvent getDeathSound() {
		return ownSound(DEATH, super.getDeathSound());
	}

	@Override
	public boolean doHurtTarget(ServerLevel level, Entity target) {
		Animator animator = animator();
		if (animator != null) {
			animator.playAnimation("attack", 10, true);
		}
		return super.doHurtTarget(level, target);
	}

	@Override
	public EntityDimensions getDefaultDimensions(Pose pose) {
		MobDefinition definition = this.applied;
		return definition == null ? super.getDefaultDimensions(pose) : EntityDimensions.scalable(definition.width(), definition.height());
	}

	@Override
	public AnimatedEntityHolder getHolder() {
		return this.holder;
	}

	@Override
	public void onSyncedDataUpdated(EntityDataAccessor<?> data) {
		super.onSyncedDataUpdated(data);
		if (this.holder != null) {
			this.holder.onSyncedDataUpdated(data, this.getEntityData().get(data));
		}
	}

	@Override
	public void refreshDimensions() {
		super.refreshDimensions();
		if (this.holder != null) {
			this.holder.onDimensionsUpdated(getDimensions(getPose()));
		}
	}
}
