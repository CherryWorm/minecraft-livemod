package gm.conduit.slots;

import net.minecraft.core.component.DataComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.world.Container;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.List;

/**
 * A machine's inventory on a chest's screen: its inputs and fuel from the left, its outputs at the right, and panes in between.
 * It uses the game's own screen, so it needs nothing on a player's computer.
 */
final class MachineMenu extends AbstractContainerMenu {
	private static final List<MenuType<?>> BY_ROWS = List.of(MenuType.GENERIC_9x1, MenuType.GENERIC_9x2, MenuType.GENERIC_9x3, MenuType.GENERIC_9x4, MenuType.GENERIC_9x5, MenuType.GENERIC_9x6);
	private static final int ROW = 9;

	private final SlotBlockEntity machine;
	private final int size;

	MachineMenu(int id, Inventory inventory, SlotBlockEntity machine, MachineInventories.Layout layout) {
		super(BY_ROWS.get(rows(layout) - 1), id);
		this.machine = machine;
		this.size = rows(layout) * ROW;
		SimpleContainer panes = new SimpleContainer(this.size);
		int outputsFrom = this.size - layout.outputs();
		for (int position = 0; position < this.size; position++) {
			int shown = layout.width() > 0 ? gridSlot(layout, position) : flowingSlot(layout, position, outputsFrom);
			if (shown >= 0) {
				addSlot(new Held(machine, shown, layout.isOutput(shown)));
			} else {
				panes.setItem(position, pane());
				addSlot(new Pane(panes, position));
			}
		}
		addStandardInventorySlots(inventory, 0, 0);
	}

	private static int rows(MachineInventories.Layout layout) {
		int flowing = (Math.max(layout.size(), 1) - 1) / ROW + 1;
		return layout.width() > 0 ? Math.max(Math.max(1, (layout.inputs() + layout.width() - 1) / layout.width()), Math.max(layout.fuel(), layout.outputs())) : flowing;
	}

	/** Inputs and fuel from the left, and outputs from the right. It returns which of its slots goes at this place, or -1 for none. */
	private static int flowingSlot(MachineInventories.Layout layout, int position, int outputsFrom) {
		int kept = layout.inputs() + layout.fuel();
		return position < kept ? position : position >= outputsFrom ? kept + position - outputsFrom : -1;
	}

	/** Its inputs as a grid, its fuel in a column beside that, and its outputs down the right. */
	private static int gridSlot(MachineInventories.Layout layout, int position) {
		int column = position % ROW;
		int row = position / ROW;
		int input = row * layout.width() + column;
		if (column < layout.width() && input < layout.inputs()) {
			return input;
		}
		if (column == ROW - 2 && row < layout.fuel()) {
			return layout.inputs() + row;
		}
		return column == ROW - 1 && row < layout.outputs() ? layout.inputs() + layout.fuel() + row : -1;
	}

	private static ItemStack pane() {
		ItemStack pane = new ItemStack(Items.GLASS_PANE);
		pane.set(DataComponents.CUSTOM_NAME, Component.empty());
		return pane;
	}

	private static final class Held extends Slot {
		private final SlotBlockEntity machine;
		private final boolean output;

		Held(SlotBlockEntity machine, int slot, boolean output) {
			super(machine, slot, 0, 0);
			this.machine = machine;
			this.output = output;
		}

		@Override
		public boolean mayPlace(ItemStack stack) {
			return !this.output && this.container.canPlaceItem(getContainerSlot(), stack);
		}

		@Override
		public int getMaxStackSize() {
			return this.machine.limitOf(getContainerSlot());
		}

		@Override
		public boolean mayPickup(Player player) {
			return this.machine.mayTake(getContainerSlot(), player);
		}

		@Override
		public void onTake(Player player, ItemStack stack) {
			super.onTake(player, stack);
			this.machine.taken(getContainerSlot(), stack, player);
		}
	}

	private static final class Pane extends Slot {
		Pane(Container container, int slot) {
			super(container, slot, 0, 0);
		}

		@Override
		public boolean mayPlace(ItemStack stack) {
			return false;
		}

		@Override
		public boolean mayPickup(Player player) {
			return false;
		}
	}

	@Override
	public ItemStack quickMoveStack(Player player, int index) {
		Slot slot = this.slots.get(index);
		if (!slot.hasItem() || !slot.mayPickup(player)) {
			return ItemStack.EMPTY;
		}
		ItemStack stack = slot.getItem();
		ItemStack before = stack.copy();
		boolean moved = false;
		if (index < this.size) {
			moved = moveItemStackTo(stack, this.size, this.slots.size(), true);
		} else {
			// One at a time, because the game adds to anything holding the same item, even an output that nothing can go in.
			for (int place = 0; place < this.size && !stack.isEmpty(); place++) {
				if (this.slots.get(place).mayPlace(stack)) {
					moved |= moveItemStackTo(stack, place, place + 1, false);
				}
			}
		}
		if (!moved) {
			return ItemStack.EMPTY;
		}
		if (stack.isEmpty()) {
			slot.setByPlayer(ItemStack.EMPTY);
		} else {
			slot.setChanged();
		}
		if (index < this.size) {
			slot.onTake(player, before.copyWithCount(before.getCount() - stack.getCount()));
		}
		return before;
	}

	@Override
	public boolean stillValid(Player player) {
		return this.machine.stillValid(player);
	}
}
