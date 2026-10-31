package gm.conduit.slots;

import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.holder.base.AbstractAnimationHolder;
import eu.pb4.polymer.virtualentity.api.attachment.BlockBoundAttachment;
import gm.conduit.api.MachineBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;

import java.util.function.Consumer;

/**
 * Generic machine storage. Modules can be replaced at any time, so everything a machine remembers lives
 * in this one tag, which survives a module being swapped or removed.
 */
public final class SlotBlockEntity extends BlockEntity {
	private CompoundTag data = new CompoundTag();

	public SlotBlockEntity(BlockPos pos, BlockState state) {
		super(NeutralSlots.machineEntityType(), pos, state);
	}

	/** The machine's saved state. Call {@link #setChanged()} after changing it. */
	public CompoundTag data() {
		return this.data;
	}

	/** Plays one of this machine's model animations by name. It does nothing on a machine that's a plain cube. */
	public void play(String animation) {
		withAnimator(animator -> animator.playAnimation(animation));
	}

	public void stop(String animation) {
		withAnimator(animator -> animator.stopAnimation(animation));
	}

	private void withAnimator(Consumer<Animator> action) {
		if (this.level != null && !this.level.isClientSide()) {
			BlockBoundAttachment attachment = BlockBoundAttachment.get(this.level, getBlockPos());
			if (attachment != null && attachment.holder() instanceof AbstractAnimationHolder holder) {
				action.accept(holder.getAnimator());
			}
		}
	}

	void tick(String slotId) {
		MachineBehavior behavior = ServerModuleHost.instance().machineBehavior(slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId, () -> behavior.tick(this));
		}
	}

	@Override
	protected void saveAdditional(ValueOutput output) {
		super.saveAdditional(output);
		output.store("machine", CompoundTag.CODEC, this.data);
	}

	@Override
	protected void loadAdditional(ValueInput input) {
		super.loadAdditional(input);
		this.data = input.read("machine", CompoundTag.CODEC).orElseGet(CompoundTag::new);
	}
}
