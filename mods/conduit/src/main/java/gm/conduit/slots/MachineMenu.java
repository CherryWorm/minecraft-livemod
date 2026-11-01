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
	private static final List<MenuType<?>> BY_ROWS = List.of(MenuType.GENERIC_9x1, MenuType.GENERIC_9x2, MenuType.GENERIC_9x3);
	private static final int ROW = 9;

	private final SlotBlockEntity machine;
	private final int size;

	MachineMenu(int id, Inventory inventory, SlotBlockEntity machine, MachineInventories.Layout layout) {
		super(BY_ROWS.get((Math.max(layout.size(), 1) - 1) / ROW), id);
		this.machine = machine;
		this.size = (Math.max(layout.size(), 1) - 1) / ROW * ROW + ROW;
		SimpleContainer panes = new SimpleContainer(this.size);
		int outputsFrom = this.size - layout.outputs();
		for (int position = 0; position < this.size; position++) {
			int kept = layout.inputs() + layout.fuel();
			if (position < kept) {
				addSlot(new Held(machine, position, false));
			} else if (position >= outputsFrom) {
				addSlot(new Held(machine, kept + position - outputsFrom, true));
			} else {
				panes.setItem(position, pane());
				addSlot(new Pane(panes, position));
			}
		}
		addStandardInventorySlots(inventory, 0, 0);
	}

	private static ItemStack pane() {
		ItemStack pane = new ItemStack(Items.GLASS_PANE);
		pane.set(DataComponents.CUSTOM_NAME, Component.empty());
		return pane;
	}

	private static final class Held extends Slot {
		private final boolean output;

		Held(Container container, int slot, boolean output) {
			super(container, slot, 0, 0);
			this.output = output;
		}

		@Override
		public boolean mayPlace(ItemStack stack) {
			return !this.output && this.container.canPlaceItem(getContainerSlot(), stack);
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
		boolean moved = index < this.size
				? moveItemStackTo(stack, this.size, this.slots.size(), true)
				: moveItemStackTo(stack, 0, this.size, false);
		if (!moved) {
			return ItemStack.EMPTY;
		}
		if (stack.isEmpty()) {
			slot.setByPlayer(ItemStack.EMPTY);
		} else {
			slot.setChanged();
		}
		return before;
	}

	@Override
	public boolean stillValid(Player player) {
		return this.machine.stillValid(player);
	}
}
