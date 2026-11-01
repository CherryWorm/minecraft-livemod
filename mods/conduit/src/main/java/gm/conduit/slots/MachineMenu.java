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
