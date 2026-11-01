package gm.conduit.entities;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.api.AnimatedEntityHolder;
import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.model.Model;
import eu.pb4.polymer.virtualentity.api.attachment.EntityAttachment;
import gm.conduit.api.ProjectileBehavior;
import gm.conduit.mobs.SlotMobs;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.core.particles.SimpleParticleType;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.sounds.SoundSource;
import net.minecraft.util.Mth;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityDimensions;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.Pose;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.world.entity.projectile.ProjectileUtil;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/**
 * A shot from something, with a model of its own. Unlike an arrow there's nothing to pick up, and unlike a snowball or a fireball it
 * does nothing at all to whatever block it lands on, so a builder can't make one that wrecks a base by accident. All the damage it
 * can do is in its definition, which the release gates hold to the stage it's in.
 */
public final class SlotProjectile extends Projectile implements AnimatedEntity {
	private static final String IDLE = "idle";
	private static final String SHOOT = "shoot";
	private static final String HIT = "hit";
	private static final float WATER_DRAG = 0.8F;
	private static final float RADIANS_TO_DEGREES = Mth.RAD_TO_DEG;
	private static final int TRAIL_SPEED = 0;
	/** A shot crosses ten chunks in a few seconds, so its model's positions are blended over less time than a mob's. */
	private static final int BLENDED_TICKS = 2;

	private TurningHolder<SlotProjectile> holder;
	private ProjectileDefinition applied;
	private float damageShare = 1.0F;
	private boolean launched;
	private int flown;

	public SlotProjectile(EntityType<? extends Projectile> type, Level level) {
		super(type, level);
		if (!level.isClientSide()) {
			ProjectileDefinition definition = SlotEntities.projectile(type);
			if (definition != null) {
				apply(definition);
			}
		}
	}

	private String slotId() {
		return BuiltInRegistries.ENTITY_TYPE.getKey(getType()).getPath();
	}

	private void apply(ProjectileDefinition definition) {
		this.applied = definition;
		refreshDimensions();
		if (this.holder != null) {
			this.holder.destroy();
			this.holder = null;
		}
		Model model = SlotMobs.model(definition.model());
		if (model != null) {
			this.holder = new TurningHolder<>(this, model);
			EntityAttachment.ofTicking(this.holder, this);
			if (model.animations().containsKey(IDLE)) {
				this.holder.getAnimator().playAnimation(IDLE, 1, true);
			}
		}
	}

	/** Sends it off in this direction at its own speed. One that's never sent off, by a command say, just hangs there. */
	void launch(Vec3 direction) {
		this.launched = true;
		setDeltaMovement(direction.normalize().scale(this.applied.speed()));
		faceMovement();
		playOwnSound(SHOOT);
	}

	/** Makes this shot weaker than its definition, say for a bow that was only half drawn. It can't make it any stronger. */
	public void weaken(float share) {
		this.damageShare = Mth.clamp(share, 0.0F, 1.0F);
	}

	public double damage() {
		return this.applied == null ? 0.0 : this.applied.damage() * this.damageShare;
	}

	public Animator animator() {
		return this.holder == null ? null : this.holder.getAnimator();
	}

	/** A projectile's own idea of its rotation is mirrored from the rest of the game's, so it's worked out here for a model to go by. */
	private void faceMovement() {
		Vec3 motion = getDeltaMovement();
		if (motion.lengthSqr() > 0.0) {
			setYRot((float) (Mth.atan2(-motion.x, motion.z) * RADIANS_TO_DEGREES));
			setXRot((float) (-Mth.atan2(motion.y, motion.horizontalDistance()) * RADIANS_TO_DEGREES));
		}
	}

	@Override
	public void tick() {
		if (level().isClientSide()) {
			super.tick();
			return;
		}
		ProjectileDefinition current = SlotEntities.projectile(getType());
		if (current == null) {
			discard();
			return;
		}
		// A release may have changed it in flight.
		if (current != this.applied && !current.equals(this.applied)) {
			apply(current);
		}
		ProjectileBehavior behavior = ServerModuleHost.instance().projectileBehavior(slotId());
		if (this.launched && ++this.flown > current.lifetime()) {
			if (behavior != null) {
				ServerModuleHost.instance().guarded(slotId(), () -> behavior.expired(this));
			}
			discard();
			return;
		}
		if (this.launched) {
			applyGravity();
			if (isInWater()) {
				setDeltaMovement(getDeltaMovement().scale(WATER_DRAG));
			}
		}
		HitResult result = ProjectileUtil.getHitResultOnMoveVector(this, this::canHitEntity);
		setPos(result.getType() == HitResult.Type.MISS ? position().add(getDeltaMovement()) : result.getLocation());
		if (this.launched) {
			faceMovement();
		}
		super.tick();
		if (current.trail() != null && this.launched && level() instanceof ServerLevel level
				&& BuiltInRegistries.PARTICLE_TYPE.getValue(current.trail()) instanceof SimpleParticleType trail) {
			// Forced, or nobody more than a few blocks away would ever see the line it draws.
			level.sendParticles(trail, true, true, getX(), getY(), getZ(), 1, 0.0, 0.0, 0.0, TRAIL_SPEED);
		}
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.tick(this));
		}
		if (result.getType() != HitResult.Type.MISS && isAlive()) {
			hitTargetOrDeflectSelf(result);
		}
	}

	@Override
	protected double getDefaultGravity() {
		return this.applied == null ? 0.0 : this.applied.gravity();
	}

	@Override
	protected void onHit(HitResult result) {
		super.onHit(result);
		playOwnSound(HIT);
		discard();
	}

	@Override
	protected void onHitEntity(EntityHitResult hit) {
		Entity target = hit.getEntity();
		float amount = (float) damage();
		boolean hurt = amount > 0.0F && level() instanceof ServerLevel level && target.hurtServer(level, damageSources().thrown(this, getOwner()), amount);
		ProjectileBehavior behavior = ServerModuleHost.instance().projectileBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.hitEntity(this, target, hurt));
		}
	}

	/** Leaves out what the game does here, which is how a chorus flower, a pot or dripstone gets broken, and TNT gets lit. */
	@Override
	protected void onHitBlock(BlockHitResult hit) {
		ProjectileBehavior behavior = ServerModuleHost.instance().projectileBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.hitBlock(this, hit));
		}
	}

	@Override
	public boolean mayInteract(ServerLevel level, BlockPos pos) {
		return false;
	}

	@Override
	public boolean mayBreak(ServerLevel level, BlockPos pos) {
		return false;
	}

	@Override
	public boolean fireImmune() {
		return true;
	}

	@Override
	public boolean canUsePortal(boolean ignorePassenger) {
		return false;
	}

	/** Nothing a shot is hit by can do anything to it, least of all give it to someone. */
	@Override
	public boolean hurtServer(ServerLevel level, DamageSource source, float amount) {
		return false;
	}

	@Override
	protected void defineSynchedData(SynchedEntityData.Builder entityData) {}

	private void playOwnSound(String kind) {
		SoundEvent sound = this.applied == null ? null : this.applied.sounds().get(kind);
		if (sound != null) {
			level().playSound(null, getX(), getY(), getZ(), sound, SoundSource.NEUTRAL, 1.0F, 1.0F);
		}
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
	public float getShadowRadius() {
		return 0.0F;
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
