package gm.conduit.slots;

import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.holder.base.AbstractAnimationHolder;
import de.tomalbrc.bil.core.model.Animation;
import eu.pb4.polymer.virtualentity.api.attachment.BlockBoundAttachment;
import gm.conduit.api.MachineBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.NonNullList;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.ContainerHelper;
import net.minecraft.world.Containers;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.WorldlyContainer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;

import java.util.function.Consumer;
import java.util.stream.IntStream;

/**
 * Generic machine storage. Modules can be replaced at any time, so everything a machine remembers lives
 * in this one tag, which survives a module being swapped or removed. If its feature gives it an inventory,
 * it's also a container like a furnace: hoppers fill its inputs from above and its fuel from the sides, and take its outputs from below.
 */
public final class SlotBlockEntity extends BlockEntity implements WorldlyContainer {
	/** The largest inventory the gates allow, so a release can change one without anything having to move. */
	private static final int MOST_SLOTS = 27;
	private static final int HELD_PRIORITY = 100;

	private CompoundTag data = new CompoundTag();
	private final NonNullList<ItemStack> items = NonNullList.withSize(MOST_SLOTS, ItemStack.EMPTY);
	private String shownAnimation;
	private float shownFraction;

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
		if (animation.equals(this.shownAnimation)) {
			this.shownAnimation = null;
			setChanged();
		}
		withAnimator(animator -> animator.stopAnimation(animation));
	}

	/**
	 * Holds one of its model's animations at a point along it, from 0 to 1, so a gauge can show a value instead of needing an
	 * animation for each reading. Call it again whenever the value changes. It stays there until {@link #stop} is called.
	 */
	public void show(String animation, float fraction) {
		this.shownAnimation = animation;
		this.shownFraction = Math.clamp(fraction, 0.0F, 1.0F);
		holdShown();
		setChanged();
	}

	/** A paused animation shows nothing at all, only the resting pose, so this one keeps playing and gets put back at the same frame every tick. */
	private void holdShown() {
		if (this.shownAnimation == null || this.level == null || this.level.isClientSide()) {
			return;
		}
		BlockBoundAttachment attachment = BlockBoundAttachment.get(this.level, getBlockPos());
		if (attachment != null && attachment.holder() instanceof AbstractAnimationHolder holder) {
			Animation animation = holder.getModel().animations().get(this.shownAnimation);
			if (animation != null) {
				holder.getAnimator().playAnimation(this.shownAnimation, HELD_PRIORITY);
				holder.getAnimator().setAnimationFrame(this.shownAnimation, Math.round(this.shownFraction * (animation.frames().length - 1)));
			}
		}
	}

	/** Opens its inventory on a chest's screen for a player. It's the same inventory hoppers use. */
	public void openMenu(ServerPlayer player, Component title) {
		player.openMenu(new SimpleMenuProvider((id, inventory, who) -> new MachineMenu(id, inventory, this, layout()), title));
	}

	private MachineInventories.Layout layout() {
		return getBlockState().getBlock() instanceof SlotBlock block ? MachineInventories.layout(block.slotId()) : MachineInventories.layout("");
	}

	@Override
	public int getContainerSize() {
		return layout().size();
	}

	@Override
	public boolean isEmpty() {
		return this.items.stream().allMatch(ItemStack::isEmpty);
	}

	@Override
	public ItemStack getItem(int slot) {
		return this.items.get(slot);
	}

	@Override
	public ItemStack removeItem(int slot, int count) {
		ItemStack taken = ContainerHelper.removeItem(this.items, slot, count);
		if (!taken.isEmpty()) {
			setChanged();
		}
		return taken;
	}

	@Override
	public ItemStack removeItemNoUpdate(int slot) {
		return ContainerHelper.takeItem(this.items, slot);
	}

	@Override
	public void setItem(int slot, ItemStack stack) {
		this.items.set(slot, stack);
		stack.limitSize(getMaxStackSize(stack));
		setChanged();
	}

	@Override
	public boolean stillValid(Player player) {
		return Container.stillValidBlockEntity(this, player);
	}

	@Override
	public void clearContent() {
		this.items.clear();
		setChanged();
	}

	@Override
	public boolean canPlaceItem(int slot, ItemStack stack) {
		if (layout().isOutput(slot) || !(getBlockState().getBlock() instanceof SlotBlock block)) {
			return false;
		}
		MachineBehavior behavior = ServerModuleHost.instance().machineBehavior(block.slotId());
		return behavior == null || ServerModuleHost.instance().guarded(block.slotId(), false, () -> behavior.accepts(this, slot, stack));
	}

	@Override
	public int[] getSlotsForFace(Direction side) {
		MachineInventories.Layout layout = layout();
		return switch (side) {
			case UP -> IntStream.range(0, layout.inputs()).toArray();
			case DOWN -> IntStream.range(layout.inputs() + layout.fuel(), layout.size()).toArray();
			default -> IntStream.range(layout.fuel() > 0 ? layout.inputs() : 0, layout.inputs() + layout.fuel()).toArray();
		};
	}

	@Override
	public boolean canPlaceItemThroughFace(int slot, ItemStack stack, Direction side) {
		return canPlaceItem(slot, stack);
	}

	@Override
	public boolean canTakeItemThroughFace(int slot, ItemStack stack, Direction side) {
		return layout().isOutput(slot);
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
		holdShown();
		MachineBehavior behavior = ServerModuleHost.instance().machineBehavior(slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(slotId, () -> behavior.tick(this));
		}
	}

	@Override
	public void preRemoveSideEffects(BlockPos pos, BlockState state) {
		super.preRemoveSideEffects(pos, state);
		if (state.getBlock() instanceof SlotBlock block) {
			MachineBehavior behavior = ServerModuleHost.instance().machineBehavior(block.slotId());
			if (behavior != null) {
				ServerModuleHost.instance().guarded(block.slotId(), () -> behavior.removed(this));
			}
		}
		if (this.level != null) {
			Containers.dropContents(this.level, pos, this.items);
		}
	}

	@Override
	protected void saveAdditional(ValueOutput output) {
		super.saveAdditional(output);
		output.store("machine", CompoundTag.CODEC, this.data);
		ContainerHelper.saveAllItems(output, this.items, false);
		if (this.shownAnimation != null) {
			output.putString("shown", this.shownAnimation);
			output.putFloat("shown_at", this.shownFraction);
		}
	}

	@Override
	protected void loadAdditional(ValueInput input) {
		super.loadAdditional(input);
		this.data = input.read("machine", CompoundTag.CODEC).orElseGet(CompoundTag::new);
		ContainerHelper.loadAllItems(input, this.items);
		this.shownAnimation = input.getString("shown").orElse(null);
		this.shownFraction = input.getFloatOr("shown_at", 0.0F);
	}
}
