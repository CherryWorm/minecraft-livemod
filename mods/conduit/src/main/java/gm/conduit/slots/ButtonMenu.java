package gm.conduit.slots;

import gm.conduit.api.MenuBehavior;
import gm.conduit.api.MenuView;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;

import java.util.List;
import java.util.function.Consumer;

/** A chest's screen where nothing moves. Every click on a slot in it goes to a module, and the player's own inventory below works as usual. */
public final class ButtonMenu extends AbstractContainerMenu implements MenuView {
	private static final List<MenuType<?>> BY_ROWS = List.of(MenuType.GENERIC_9x1, MenuType.GENERIC_9x2, MenuType.GENERIC_9x3,
			MenuType.GENERIC_9x4, MenuType.GENERIC_9x5, MenuType.GENERIC_9x6);
	private static final int RIGHT_BUTTON = 1;

	private final ServerPlayer player;
	private final SimpleContainer shown;
	private final MenuBehavior behavior;
	private final Consumer<Runnable> guard;

	/** @param guard runs a module's code, so one that keeps failing gets switched off the same as anywhere else */
	public ButtonMenu(int id, Inventory inventory, ServerPlayer player, int rows, MenuBehavior behavior, Consumer<Runnable> guard) {
		super(BY_ROWS.get(rows - 1), id);
		this.player = player;
		this.behavior = behavior;
		this.guard = guard;
		this.shown = new SimpleContainer(rows * 9);
		for (int slot = 0; slot < this.shown.getContainerSize(); slot++) {
			addSlot(new Picture(this.shown, slot));
		}
		addStandardInventorySlots(inventory, 0, 0);
		guard.accept(() -> behavior.draw(this));
	}

	private static final class Picture extends Slot {
		Picture(SimpleContainer container, int slot) {
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
	public void clicked(int slot, int button, ContainerInput input, Player clicker) {
		if (slot < 0 || slot >= size()) {
			super.clicked(slot, button, input, clicker);
			return;
		}
		// Only a press counts, so a drag or a double click isn't taken for several presses.
		if (input == ContainerInput.PICKUP || input == ContainerInput.QUICK_MOVE) {
			this.guard.accept(() -> {
				this.behavior.clicked(this, slot, button == RIGHT_BUTTON, input == ContainerInput.QUICK_MOVE);
				this.behavior.draw(this);
			});
		}
		// The client has already moved the item in its own mind, so it has to be told again.
		sendAllDataToRemote();
	}

	@Override
	public ItemStack quickMoveStack(Player clicker, int slot) {
		return ItemStack.EMPTY;
	}

	@Override
	public boolean stillValid(Player clicker) {
		return true;
	}

	@Override
	public void removed(Player clicker) {
		super.removed(clicker);
		this.guard.accept(() -> this.behavior.closed(this));
	}

	@Override
	public ServerPlayer player() {
		return this.player;
	}

	@Override
	public int size() {
		return this.shown.getContainerSize();
	}

	@Override
	public ItemStack get(int slot) {
		return this.shown.getItem(slot);
	}

	@Override
	public void set(int slot, ItemStack stack) {
		this.shown.setItem(slot, stack);
	}

	@Override
	public void close() {
		this.player.closeContainer();
	}
}
