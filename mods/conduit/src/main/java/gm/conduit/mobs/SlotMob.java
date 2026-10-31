package gm.conduit.mobs;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.api.AnimatedEntityHolder;
import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.holder.entity.living.LivingEntityHolder;
import eu.pb4.polymer.virtualentity.api.attachment.EntityAttachment;
import gm.conduit.api.MobBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityDimensions;
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
import net.minecraft.world.entity.ai.goal.WaterAvoidingRandomStrollGoal;
import net.minecraft.world.entity.ai.goal.target.HurtByTargetGoal;
import net.minecraft.world.entity.ai.goal.target.NearestAttackableTargetGoal;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;

/**
 * A creature with no fixed identity. Its type is one of a fixed pool registered at boot, and everything else
 * comes from the current release: looks, size, stats, behaviour, so a new mob needs no restart. A slot with
 * nothing bound removes itself rather than standing around invisible.
 */
public final class SlotMob extends PathfinderMob implements AnimatedEntity {
	private LivingEntityHolder<SlotMob> holder;
	private MobDefinition applied;

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
		refreshDimensions();
		if (this.holder != null) {
			this.holder.destroy();
			this.holder = null;
		}
		var model = SlotMobs.model(definition.model());
		if (model != null) {
			this.holder = new LivingEntityHolder<>(this, model);
			EntityAttachment.ofTicking(this.holder, this);
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
		this.goalSelector.addGoal(5, new WaterAvoidingRandomStrollGoal(this, 0.8));
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
		if (this.tickCount % 2 == 0) {
			updateAnimation();
		}
		MobBehavior behavior = ServerModuleHost.instance().mobBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.tick(this));
		}
	}

	private void updateAnimation() {
		Animator animator = animator();
		if (animator == null) {
			return;
		}
		if (this.walkAnimation.isMoving() && this.walkAnimation.speed() > 0.02F) {
			animator.pauseAnimation("idle");
			animator.playAnimation("walk", 5);
		} else {
			animator.pauseAnimation("walk");
			animator.playAnimation("idle", 1, true);
		}
	}

	@Override
	public boolean hurtServer(ServerLevel level, DamageSource source, float amount) {
		MobBehavior behavior = ServerModuleHost.instance().mobBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.hurt(this, source));
		}
		return super.hurtServer(level, source, amount);
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
