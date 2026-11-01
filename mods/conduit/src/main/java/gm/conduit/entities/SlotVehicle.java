package gm.conduit.entities;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.api.AnimatedEntityHolder;
import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.model.Animation;
import de.tomalbrc.bil.core.model.Model;
import eu.pb4.polymer.virtualentity.api.attachment.EntityAttachment;
import gm.conduit.api.VehicleBehavior;
import gm.conduit.mobs.SlotMobs;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.protocol.game.ClientboundPlayerRotationPacket;
import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.sounds.SoundSource;
import net.minecraft.tags.FluidTags;
import net.minecraft.util.Mth;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityDimensions;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.Pose;
import net.minecraft.world.entity.player.Input;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.gamerules.GameRules;
import net.minecraft.world.level.material.FluidState;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;
import net.minecraft.world.phys.Vec3;

/**
 * Something a player rides and steers. The server moves it, from the keys its rider's client reports.
 * <p>
 * A real boat is moved by its rider's client, with its speed written into the client's code, so its 8 blocks a second is out of reach from
 * here. A horse's client takes its speed from an attribute a server can set, but a rider gets a horse's physics and its place on the screen
 * with it, and nothing like it can float. A client sees this as an entity it has no way to drive, so it sends only its keys and where it's
 * looking, and draws the rider wherever it's told to. That means every number here is the server's to set. The price is that the rider's keys
 * take one trip to the server and back to show, where a real boat answers at once however bad the connection is.
 */
public final class SlotVehicle extends Entity implements AnimatedEntity {
	private static final String IDLE = "idle";
	private static final String WALK = "walk";
	private static final String HURT = "hurt";
	private static final String MOVE_SOUND = "move";
	private static final String HURT_SOUND = "hurt";
	private static final String BREAK_SOUND = "break";
	private static final int MOVE_SOUND_EVERY = 20;
	private static final double STILL = 0.005;
	/** How much of a boat's height sits below the water. */
	private static final double DRAFT = 0.35;
	private static final double FLOAT_RATE = 0.25;
	private static final double MOST_BOB = 0.2;
	private static final double SINK_RATE = 0.8;
	/** Falls this slowly from the air with nobody flying it, so that a player who gets off doesn't lose it. */
	private static final double UNPILOTED_FALL = 0.1;
	/** A rider's view turns with the vehicle, up to this much a tick. Any faster would be a lurch rather than a turn, so past this their view falls behind. */
	private static final float MOST_CAMERA_TURN = 20.0F;
	private static final double STOP_ON_CRASH = 0.5;
	/** The same thing's position gets blended over this many ticks, on every client. Lower is more responsive, and higher is smoother. */
	private static final int BLENDED_TICKS = 2;

	private VehicleHolder holder;
	private VehicleDefinition applied;
	private final HeldPose heldPose = new HeldPose();
	private float health;
	/** Its speed in the direction it's facing, in blocks a tick. */
	private double forward;
	private float speedShare = 1.0F;
	/** Null until its model has been told to do anything, so that a new one starts out right. */
	private Boolean wasMoving;

	public SlotVehicle(EntityType<? extends SlotVehicle> type, Level level) {
		super(type, level);
		if (!level.isClientSide()) {
			VehicleDefinition definition = SlotEntities.vehicle(type);
			if (definition != null) {
				apply(definition);
				this.health = definition.health();
			}
		}
	}

	private String slotId() {
		return BuiltInRegistries.ENTITY_TYPE.getKey(getType()).getPath();
	}

	private void apply(VehicleDefinition definition) {
		this.applied = definition;
		this.wasMoving = null;
		refreshDimensions();
		if (this.holder != null) {
			this.holder.destroy();
			this.holder = null;
		}
		Model model = SlotMobs.model(definition.model());
		if (model != null) {
			this.holder = new VehicleHolder(this, model, definition.seat());
			EntityAttachment.ofTicking(this.holder, this);
		}
	}

	/** Holds it to some share of its speed, say for one out of fuel, from 0 for not at all up to 1 for all of it. It can't make it go any faster. */
	public void limitSpeed(float share) {
		this.speedShare = Mth.clamp(share, 0.0F, 1.0F);
	}

	public Player rider() {
		return getFirstPassenger() instanceof Player player ? player : null;
	}

	public Animator animator() {
		return this.holder == null ? null : this.holder.getAnimator();
	}

	public Animation animation(String name) {
		Model model = this.applied == null ? null : SlotMobs.model(this.applied.model());
		return model == null ? null : model.animations().get(name);
	}

	/** See {@link gm.conduit.mobs.SlotMob#pose}. */
	public boolean pose(String name, float fraction) {
		return this.heldPose.start(animator(), animation(name), name, fraction);
	}

	@Override
	public void tick() {
		super.tick();
		if (level().isClientSide()) {
			return;
		}
		VehicleDefinition current = SlotEntities.vehicle(getType());
		if (current == null) {
			discard();
			return;
		}
		// A release may have changed it while it was out.
		if (current != this.applied && !current.equals(this.applied)) {
			apply(current);
			this.health = Math.min(this.health, current.health());
		}
		Input keys = getFirstPassenger() instanceof ServerPlayer player ? player.getLastClientInput() : Input.EMPTY;
		steer(current, keys);
		Vec3 motion = motion(current, keys);
		if (level().hasChunkAt(BlockPos.containing(position().add(motion)))) {
			setDeltaMovement(motion);
			move(MoverType.SELF, motion);
			if (this.horizontalCollision) {
				this.forward *= STOP_ON_CRASH;
			}
		} else {
			// Moving into land that isn't there would drop it straight through.
			this.forward = 0.0;
			setDeltaMovement(Vec3.ZERO);
		}
		updateAnimation(current);
		VehicleBehavior behavior = ServerModuleHost.instance().vehicleBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.tick(this));
		}
	}

	private void steer(VehicleDefinition definition, Input keys) {
		if (!(getFirstPassenger() instanceof ServerPlayer rider)) {
			return;
		}
		float before = getYRot();
		if (definition.steersByKeys()) {
			setYRot(before + ((keys.right() ? 1 : 0) - (keys.left() ? 1 : 0)) * definition.turn() * (this.forward < 0.0 ? -1 : 1));
			float turned = Mth.clamp(getYRot() - before, -MOST_CAMERA_TURN, MOST_CAMERA_TURN);
			if (turned != 0.0F) {
				rider.connection.send(new ClientboundPlayerRotationPacket(turned, true, 0.0F, true));
			}
		} else {
			setYRot(Mth.approachDegrees(before, rider.getYRot(), definition.turn()));
		}
	}

	private Vec3 motion(VehicleDefinition definition, Input keys) {
		double wanted = keys.forward() ? definition.speed() : keys.backward() ? -definition.reverse() : 0.0;
		wanted *= this.speedShare;
		double up = getDeltaMovement().y;
		switch (definition.moves()) {
			case VehicleDefinition.WATER -> {
				double surface = waterSurface();
				if (Double.isNaN(surface)) {
					up -= definition.gravity();
					wanted *= onGround() ? definition.landShare() : 1.0;
				} else {
					up = Mth.clamp((surface - definition.height() * DRAFT - getY()) * FLOAT_RATE, -MOST_BOB, MOST_BOB);
				}
			}
			case VehicleDefinition.AIR -> {
				if (rider() == null) {
					up = -UNPILOTED_FALL;
				} else {
					up = keys.jump() ? definition.climb() : keys.sprint() ? -definition.climb() : 0.0;
				}
			}
			default -> {
				if (isInWater()) {
					wanted *= definition.waterShare();
					up = (up - definition.gravity()) * SINK_RATE;
				} else {
					up -= definition.gravity();
				}
			}
		}
		this.forward = approach(this.forward, wanted, definition.acceleration());
		double yaw = getYRot() * Mth.DEG_TO_RAD;
		return new Vec3(-Math.sin(yaw) * this.forward, up, Math.cos(yaw) * this.forward);
	}

	private static double approach(double current, double target, double step) {
		return current < target ? Math.min(current + step, target) : Math.max(current - step, target);
	}

	/** The height of the top of any water it's in or just above, or NaN if there's none. */
	private double waterSurface() {
		BlockPos.MutableBlockPos at = BlockPos.containing(getX(), getBoundingBox().maxY + 1.0, getZ()).mutable();
		int bottom = Mth.floor(getBoundingBox().minY) - 1;
		for (; at.getY() >= bottom; at.move(0, -1, 0)) {
			FluidState fluid = level().getFluidState(at);
			if (fluid.is(FluidTags.WATER)) {
				return at.getY() + fluid.getHeight(level(), at);
			}
		}
		return Double.NaN;
	}

	private void updateAnimation(VehicleDefinition definition) {
		Animator animator = animator();
		boolean moving = Math.abs(this.forward) > STILL;
		if (moving && this.tickCount % MOVE_SOUND_EVERY == 0) {
			playOwnSound(MOVE_SOUND);
		}
		if (animator == null) {
			return;
		}
		if (this.heldPose.tick(animator)) {
			return;
		}
		if (this.wasMoving == null || moving != this.wasMoving) {
			this.wasMoving = moving;
			if (moving) {
				animator.pauseAnimation(IDLE);
				if (animation(WALK) != null) {
					animator.playAnimation(WALK, 5);
				}
			} else {
				animator.pauseAnimation(WALK);
				if (animation(IDLE) != null) {
					animator.playAnimation(IDLE, 1, true);
				}
			}
		}
	}

	@Override
	public InteractionResult interact(Player player, InteractionHand hand, Vec3 location) {
		if (!level().isClientSide()) {
			VehicleBehavior behavior = ServerModuleHost.instance().vehicleBehavior(slotId());
			if (behavior != null) {
				InteractionResult result = ServerModuleHost.instance().guarded(slotId(), InteractionResult.PASS, () -> behavior.interact(this, player, hand));
				if (result != InteractionResult.PASS) {
					return result;
				}
			}
		}
		if (player.isSecondaryUseActive() || hasPassenger(player) || (!level().isClientSide() && !player.startRiding(this))) {
			return InteractionResult.PASS;
		}
		return InteractionResult.SUCCESS;
	}

	@Override
	protected boolean canAddPassenger(Entity passenger) {
		return getPassengers().isEmpty() && passenger instanceof Player;
	}

	@Override
	protected void addPassenger(Entity passenger) {
		super.addPassenger(passenger);
		if (level().isClientSide() || !(passenger instanceof ServerPlayer rider)) {
			return;
		}
		if (this.holder != null) {
			this.holder.riderSeated(rider);
		}
		VehicleBehavior behavior = ServerModuleHost.instance().vehicleBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.boarded(this, rider));
		}
	}

	@Override
	protected void removePassenger(Entity passenger) {
		super.removePassenger(passenger);
		if (level().isClientSide() || !(passenger instanceof ServerPlayer rider)) {
			return;
		}
		if (this.holder != null) {
			this.holder.riderGone(rider);
		}
		VehicleBehavior behavior = ServerModuleHost.instance().vehicleBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.left(this, rider));
		}
	}

	@Override
	protected Vec3 getPassengerAttachmentPoint(Entity passenger, EntityDimensions dimensions, float scale) {
		return this.applied == null ? super.getPassengerAttachmentPoint(passenger, dimensions, scale) : new Vec3(0.0, this.applied.seat(), 0.0);
	}

	@Override
	public float maxUpStep() {
		return this.applied == null ? 0.0F : this.applied.stepHeight();
	}

	@Override
	public boolean isPickable() {
		return !isRemoved();
	}

	@Override
	public boolean causeFallDamage(double fallDistance, float damageModifier, DamageSource damageSource) {
		return false;
	}

	@Override
	public boolean hurtServer(ServerLevel level, DamageSource source, float amount) {
		if (isRemoved() || isInvulnerableToBase(source) || hasPassenger(source.getEntity())) {
			return false;
		}
		VehicleBehavior behavior = ServerModuleHost.instance().vehicleBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.hurt(this, source));
		}
		boolean creative = source.getEntity() instanceof Player player && player.getAbilities().instabuild;
		this.health -= creative ? this.health : amount;
		if (this.health > 0.0F) {
			playOwnSound(HURT_SOUND);
			if (animator() != null && animation(HURT) != null) {
				animator().playAnimation(HURT, 8, true);
			}
			return true;
		}
		playOwnSound(BREAK_SOUND);
		ejectPassengers();
		if (!creative && this.applied != null && this.applied.item() != null && level.getGameRules().get(GameRules.ENTITY_DROPS)) {
			spawnAtLocation(level, new ItemStack(this.applied.item()));
		}
		discard();
		return true;
	}

	@Override
	public ItemStack getPickResult() {
		return this.applied == null || this.applied.item() == null ? null : new ItemStack(this.applied.item());
	}

	private void playOwnSound(String kind) {
		SoundEvent sound = this.applied == null ? null : this.applied.sounds().get(kind);
		if (sound != null) {
			level().playSound(null, getX(), getY(), getZ(), sound, SoundSource.NEUTRAL, 1.0F, 1.0F);
		}
	}

	@Override
	protected void defineSynchedData(SynchedEntityData.Builder entityData) {}

	@Override
	protected void addAdditionalSaveData(ValueOutput output) {
		output.putFloat("health", this.health);
		output.putFloat("speed_share", this.speedShare);
	}

	@Override
	protected void readAdditionalSaveData(ValueInput input) {
		this.health = input.getFloatOr("health", this.health);
		this.speedShare = input.getFloatOr("speed_share", 1.0F);
	}

	@Override
	public EntityDimensions getDimensions(Pose pose) {
		return this.applied == null ? super.getDimensions(pose) : EntityDimensions.scalable(this.applied.width(), this.applied.height());
	}

	@Override
	public AnimatedEntityHolder getHolder() {
		return this.holder;
	}

	@Override
	public int getTeleportDuration() {
		return BLENDED_TICKS;
	}

	@Override
	public void onSyncedDataUpdated(EntityDataAccessor<?> data) {
		super.onSyncedDataUpdated(data);
		if (this.holder != null) {
			this.holder.onSyncedDataUpdated(data, getEntityData().get(data));
		}
	}
}
