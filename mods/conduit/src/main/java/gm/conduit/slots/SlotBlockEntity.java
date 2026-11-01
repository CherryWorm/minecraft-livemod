package gm.conduit.slots;

import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.holder.base.AbstractAnimationHolder;
import de.tomalbrc.bil.core.holder.wrapper.Bone;
import de.tomalbrc.bil.core.model.Animation;
import eu.pb4.polymer.virtualentity.api.attachment.BlockBoundAttachment;
import gm.conduit.api.MachineBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.NonNullList;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.util.Brightness;
import net.minecraft.util.Mth;
import net.minecraft.world.Container;
import net.minecraft.world.ContainerHelper;
import net.minecraft.world.Containers;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.WorldlyContainer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;

import org.joml.Quaternionf;
import org.joml.Vector3f;

import java.util.HashMap;
import java.util.Map;
import java.util.function.Consumer;
import java.util.function.UnaryOperator;
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
	/** The animations being held at a point along them, from 0 to 1. */
	private final Map<String, Float> shown = new HashMap<>();
	/** What modules have done to its model's parts, by part, kept here so it comes back with the world. */
	private CompoundTag parts = new CompoundTag();
	private boolean partsToShow;

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
		if (this.shown.remove(animation) != null) {
			setChanged();
		}
		withAnimator(animator -> animator.stopAnimation(animation));
	}

	/**
	 * Holds one of its model's animations at a point along it, from 0 to 1, so a gauge can show a value instead of needing an
	 * animation for each reading. Call it again whenever the value changes. It stays there until {@link #stop} is called. Several
	 * can be held at once, for a gauge and a lever on the same machine, as long as they don't move the same parts.
	 */
	public void show(String animation, float fraction) {
		this.shown.put(animation, Math.clamp(fraction, 0.0F, 1.0F));
		holdShown();
		setChanged();
	}

	/**
	 * Moves a named part of its model this far from where it would be, in blocks, on top of any animation. It stays until
	 * {@link #resetPart}, through a restart. Returns false if it's a cube or its model has no such part, so call it whenever the value changes.
	 */
	public boolean movePart(String part, float x, float y, float z) {
		return changePart(part, look -> look.withOffset(new Vector3f(x, y, z)), tag -> {
			tag.putFloat("x", x);
			tag.putFloat("y", y);
			tag.putFloat("z", z);
		});
	}

	/** Turns a named part this many degrees round its own origin, on top of any animation, in the same way as {@link #movePart}. */
	public boolean turnPart(String part, float pitch, float yaw, float roll) {
		return changePart(part, look -> look.withRotation(rotation(pitch, yaw, roll)), tag -> {
			tag.putFloat("pitch", pitch);
			tag.putFloat("yaw", yaw);
			tag.putFloat("roll", roll);
		});
	}

	/** Makes a named part this many times its size, on top of any animation, in the same way as {@link #movePart}. */
	public boolean scalePart(String part, float x, float y, float z) {
		return changePart(part, look -> look.withScale(new Vector3f(x, y, z)), tag -> {
			tag.putFloat("scale_x", x);
			tag.putFloat("scale_y", y);
			tag.putFloat("scale_z", z);
		});
	}

	/** Colours a named part, in the same way as {@link #movePart}. It multiplies the model's colours, so paint a part that's meant to be tinted in light greys. */
	public boolean tintPart(String part, int rgb) {
		return changePart(part, look -> look.withTint(rgb), tag -> tag.putInt("tint", rgb));
	}

	/** Makes a named part give its own light from 0 to 15, whatever's around it, in the same way as {@link #movePart}. */
	public boolean glowPart(String part, int level) {
		int glow = Math.clamp(level, 0, Brightness.FULL_BRIGHT.block());
		return changePart(part, look -> look.withGlow(glow), tag -> tag.putInt("glow", glow));
	}

	/** Puts a named part back how its model and animations say, apart from any glow in its feature. */
	public void resetPart(String part) {
		if (this.parts.contains(part)) {
			this.parts.remove(part);
			setChanged();
		}
		SlotModelHolder holder = modelHolder();
		if (holder != null) {
			holder.clearLook(part);
		}
	}

	private boolean changePart(String part, UnaryOperator<SlotModelHolder.PartLook> change, Consumer<CompoundTag> remember) {
		SlotModelHolder holder = modelHolder();
		if (holder == null || !holder.setLook(part, change.apply(holder.look(part)))) {
			return false;
		}
		CompoundTag tag = this.parts.getCompoundOrEmpty(part);
		remember.accept(tag);
		this.parts.put(part, tag);
		setChanged();
		return true;
	}

	private static Quaternionf rotation(float pitch, float yaw, float roll) {
		return new Quaternionf().rotationZYX(roll * Mth.DEG_TO_RAD, yaw * Mth.DEG_TO_RAD, pitch * Mth.DEG_TO_RAD);
	}

	private SlotModelHolder modelHolder() {
		if (this.level == null || this.level.isClientSide()) {
			return null;
		}
		BlockBoundAttachment attachment = BlockBoundAttachment.get(this.level, getBlockPos());
		return attachment != null && attachment.holder() instanceof SlotModelHolder holder ? holder : null;
	}

	/** Puts back what was saved with it, once the model is there to do it to. */
	private void showParts() {
		SlotModelHolder holder = modelHolder();
		if (holder == null) {
			return;
		}
		for (String part : this.parts.keySet()) {
			CompoundTag tag = this.parts.getCompoundOrEmpty(part);
			SlotModelHolder.PartLook look = holder.look(part)
					.withOffset(new Vector3f(tag.getFloatOr("x", 0), tag.getFloatOr("y", 0), tag.getFloatOr("z", 0)))
					.withRotation(rotation(tag.getFloatOr("pitch", 0), tag.getFloatOr("yaw", 0), tag.getFloatOr("roll", 0)))
					.withScale(new Vector3f(tag.getFloatOr("scale_x", 1), tag.getFloatOr("scale_y", 1), tag.getFloatOr("scale_z", 1)));
			look = tag.contains("tint") ? look.withTint(tag.getIntOr("tint", 0)) : look;
			holder.setLook(part, tag.contains("glow") ? look.withGlow(tag.getIntOr("glow", 0)) : look);
		}
		this.partsToShow = false;
	}

	/** Which way it faces, for one that can. Anything else says north, which is how those always look. */
	public Direction facing() {
		return getBlockState().getBlock() instanceof SlotBlock && getBlockState().hasProperty(SlotBlock.FACING) ? getBlockState().getValue(SlotBlock.FACING) : Direction.NORTH;
	}

	/** Sets how much light this one gives, from 0 to 15. It's kept with the block, so it stays through a restart. */
	public void setLight(int level) {
		if (this.level != null && getBlockState().hasProperty(SlotBlock.LIGHT)) {
			this.level.setBlock(getBlockPos(), getBlockState().setValue(SlotBlock.LIGHT, Math.clamp(level, 0, Brightness.FULL_BRIGHT.block())), Block.UPDATE_ALL);
		}
	}

	/** The strongest redstone signal reaching it from any side, from 0 to 15. */
	public int redstoneInput() {
		return this.level == null ? 0 : this.level.getBestNeighborSignal(getBlockPos());
	}

	/** How many fit in this slot, which is what its feature says or the most any stack can hold, unless a module says less. */
	public int limitOf(int slot) {
		int limit = layout().limit(slot, getMaxStackSize());
		MachineBehavior behavior = behavior();
		if (behavior == null) {
			return limit;
		}
		int fixed = limit;
		return Math.clamp(ServerModuleHost.instance().guarded(slotOf(), fixed, () -> behavior.slotLimit(this, slot, fixed)), 1, limit);
	}

	/** Whether a player can take from this slot. Only an output slot asks. */
	public boolean mayTake(int slot, Player player) {
		MachineBehavior behavior = behavior();
		return behavior == null || !layout().isOutput(slot) || ServerModuleHost.instance().guarded(slotOf(), true, () -> behavior.canTake(this, slot, player));
	}

	/** A player has just taken this from one of its slots, and only an output slot tells anyone. */
	public void taken(int slot, ItemStack stack, Player player) {
		MachineBehavior behavior = behavior();
		if (behavior != null && layout().isOutput(slot) && !stack.isEmpty()) {
			ServerModuleHost.instance().guarded(slotOf(), () -> behavior.outputTaken(this, slot, stack, player));
		}
	}

	private String slotOf() {
		return getBlockState().getBlock() instanceof SlotBlock block ? block.slotId() : "";
	}

	private MachineBehavior behavior() {
		return ServerModuleHost.instance().machineBehavior(slotOf());
	}

	/** A paused animation shows nothing at all, only the resting pose, so this one keeps playing and gets put back at the same frame every tick. */
	private void holdShown() {
		if (this.shown.isEmpty() || this.level == null || this.level.isClientSide()) {
			return;
		}
		BlockBoundAttachment attachment = BlockBoundAttachment.get(this.level, getBlockPos());
		if (attachment != null && attachment.holder() instanceof AbstractAnimationHolder holder) {
			this.shown.forEach((name, fraction) -> {
				Animation animation = holder.getModel().animations().get(name);
				if (animation != null) {
					holder.getAnimator().playAnimation(name, HELD_PRIORITY);
					holder.getAnimator().setAnimationFrame(name, Math.round(fraction * (animation.frames().length - 1)));
				}
			});
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
		stack.limitSize(Math.min(getMaxStackSize(stack), limitOf(slot)));
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
		// A hopper only asks this, then adds as long as the stack has room.
		ItemStack held = getItem(slot);
		if (!held.isEmpty() && ItemStack.isSameItem(held, stack) && held.getCount() >= limitOf(slot)) {
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
		if (this.partsToShow) {
			showParts();
		}
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
		if (!this.shown.isEmpty()) {
			CompoundTag held = new CompoundTag();
			this.shown.forEach(held::putFloat);
			output.store("shown_all", CompoundTag.CODEC, held);
		}
		if (!this.parts.isEmpty()) {
			output.store("parts", CompoundTag.CODEC, this.parts);
		}
	}

	@Override
	protected void loadAdditional(ValueInput input) {
		super.loadAdditional(input);
		this.data = input.read("machine", CompoundTag.CODEC).orElseGet(CompoundTag::new);
		ContainerHelper.loadAllItems(input, this.items);
		this.shown.clear();
		input.getString("shown").ifPresent(name -> this.shown.put(name, input.getFloatOr("shown_at", 0.0F)));
		input.read("shown_all", CompoundTag.CODEC).ifPresent(held -> held.keySet().forEach(name -> this.shown.put(name, held.getFloatOr(name, 0.0F))));
		this.parts = input.read("parts", CompoundTag.CODEC).orElseGet(CompoundTag::new);
		this.partsToShow = !this.parts.isEmpty();
	}
}
