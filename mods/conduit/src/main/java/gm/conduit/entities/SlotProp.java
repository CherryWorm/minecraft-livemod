package gm.conduit.entities;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.api.AnimatedEntityHolder;
import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.holder.entity.EntityHolder;
import de.tomalbrc.bil.core.model.Animation;
import de.tomalbrc.bil.core.model.Model;
import eu.pb4.polymer.virtualentity.api.attachment.EntityAttachment;
import gm.conduit.api.PropBehavior;
import gm.conduit.mobs.SlotMobs;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityDimensions;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.Pose;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;
import net.minecraft.world.phys.Vec3;

/**
 * A model a module puts in the world and moves around, with no block under it and nothing that acts by itself: it can be anywhere, at any
 * angle, and nothing hurts it or falls on it. It stays through a restart, and if a release stops binding its slot, it goes.
 */
public final class SlotProp extends Entity implements AnimatedEntity {
	private static final String IDLE = "idle";

	private EntityHolder<SlotProp> holder;
	private PropDefinition applied;
	private final HeldPose heldPose = new HeldPose();

	public SlotProp(EntityType<? extends SlotProp> type, Level level) {
		super(type, level);
		this.noPhysics = true;
		if (!level.isClientSide()) {
			PropDefinition definition = SlotEntities.prop(type);
			if (definition != null) {
				apply(definition);
			}
		}
	}

	private String slotId() {
		return BuiltInRegistries.ENTITY_TYPE.getKey(getType()).getPath();
	}

	private void apply(PropDefinition definition) {
		this.applied = definition;
		refreshDimensions();
		if (this.holder != null) {
			this.holder.destroy();
			this.holder = null;
		}
		Model model = SlotMobs.model(definition.model());
		if (model != null) {
			this.holder = definition.clickable() ? new ClickableHolder<>(this, model) : new TurningHolder<>(this, model);
			EntityAttachment.ofTicking(this.holder, this);
			if (model.animations().containsKey(IDLE)) {
				this.holder.getAnimator().playAnimation(IDLE, 1, true);
			}
		}
	}

	public Animator animator() {
		return this.holder == null ? null : this.holder.getAnimator();
	}

	/** Plays one of its model's animations once, over whatever else it's playing. */
	public boolean play(String name) {
		Animator animator = animator();
		if (animator == null || animation(name) == null) {
			return false;
		}
		animator.playAnimation(name, 10, true);
		return true;
	}

	/** Moves it, which every client sees smoothly over the next couple of ticks. */
	public void place(Vec3 position, float yaw, float pitch) {
		snapTo(position.x, position.y, position.z, yaw, pitch);
	}

	/** Colours its model, as with a mob's. It lasts until its next restart, so a module that wants it longer sets it again. */
	public void setTint(int rgb) {
		if (this.holder != null) {
			this.holder.setColor(rgb);
		}
	}

	public void setScale(float scale) {
		if (this.holder != null) {
			this.holder.setScale(scale);
		}
	}

	private Animation animation(String name) {
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
		PropDefinition current = SlotEntities.prop(getType());
		if (current == null) {
			discard();
			return;
		}
		// A release may have changed it while it was out.
		if (current != this.applied && !current.equals(this.applied)) {
			apply(current);
		}
		if (animator() != null) {
			this.heldPose.tick(animator());
		}
		PropBehavior behavior = ServerModuleHost.instance().propBehavior(slotId());
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId(), () -> behavior.tick(this));
		}
	}

	@Override
	public InteractionResult interact(Player player, InteractionHand hand, Vec3 location) {
		PropBehavior behavior = ServerModuleHost.instance().propBehavior(slotId());
		if (behavior != null && !level().isClientSide()) {
			return ServerModuleHost.instance().guarded(slotId(), InteractionResult.PASS, () -> behavior.interact(this, player, hand));
		}
		return InteractionResult.PASS;
	}

	@Override
	public boolean isPickable() {
		return this.applied != null && this.applied.clickable() && !isRemoved();
	}

	@Override
	public boolean hurtServer(ServerLevel level, DamageSource source, float amount) {
		return false;
	}

	@Override
	protected void defineSynchedData(SynchedEntityData.Builder entityData) {}

	@Override
	protected void addAdditionalSaveData(ValueOutput output) {}

	@Override
	protected void readAdditionalSaveData(ValueInput input) {}

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
	public void onSyncedDataUpdated(EntityDataAccessor<?> data) {
		super.onSyncedDataUpdated(data);
		if (this.holder != null) {
			this.holder.onSyncedDataUpdated(data, getEntityData().get(data));
		}
	}
}
