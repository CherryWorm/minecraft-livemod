package gm.companion;

import gm.companion.api.InventoryView;
import gm.companion.mixin.AbstractContainerScreenAccessor;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;

/**
 * What modules see of an inventory. Modules can't name LocalPlayer or the game mode, because either could act as the player in
 * any way at all, so these few clicks are the only part of that they get, and only on what's in front of the player.
 */
final class ContainerView implements InventoryView {
	private static final int HOTBAR_SIZE = 9;
	// What the server's own click packet calls these, which isn't how the mouse numbers its buttons.
	private static final int LEFT_CLICK = 0;
	private static final int RIGHT_CLICK = 1;
	private static int clicksThisTick;

	/** Null for the player's own inventory with no screen open. */
	private final AbstractContainerScreen<?> screen;
	private final AbstractContainerMenu menu;

	ContainerView(AbstractContainerScreen<?> screen, AbstractContainerMenu menu) {
		this.screen = screen;
		this.menu = menu;
	}

	static void newTick() {
		clicksThisTick = 0;
	}

	private boolean exists(int slot) {
		return slot >= 0 && slot < this.menu.slots.size();
	}

	private boolean stillOpen() {
		Minecraft client = Minecraft.getInstance();
		return client.player != null && client.gameMode != null && client.player.containerMenu == this.menu && client.gui.screen() == this.screen;
	}

	private boolean act(int slot, int button, ContainerInput input) {
		if (!exists(slot) || !stillOpen() || clicksThisTick >= MAX_CLICKS_PER_TICK) {
			return false;
		}
		clicksThisTick++;
		Minecraft client = Minecraft.getInstance();
		client.gameMode.handleContainerInput(this.menu.containerId, slot, button, input, client.player);
		return true;
	}

	@Override
	public int size() {
		return this.menu.slots.size();
	}

	@Override
	public ItemStack item(int slot) {
		return exists(slot) ? this.menu.getSlot(slot).getItem() : ItemStack.EMPTY;
	}

	@Override
	public ItemStack carried() {
		return this.menu.getCarried();
	}

	@Override
	public int slotAt(double mouseX, double mouseY) {
		if (this.screen == null) {
			return -1;
		}
		Slot slot = ((AbstractContainerScreenAccessor) this.screen).companion$slotAt(mouseX, mouseY);
		return slot == null ? -1 : slot.index;
	}

	@Override
	public int slotX(int slot) {
		return this.screen == null || !exists(slot) ? -1 : ((AbstractContainerScreenAccessor) this.screen).companion$leftPos() + this.menu.getSlot(slot).x;
	}

	@Override
	public int slotY(int slot) {
		return this.screen == null || !exists(slot) ? -1 : ((AbstractContainerScreenAccessor) this.screen).companion$topPos() + this.menu.getSlot(slot).y;
	}

	@Override
	public boolean isOwn(int slot) {
		Minecraft client = Minecraft.getInstance();
		return exists(slot) && client.player != null && this.menu.getSlot(slot).container == client.player.getInventory();
	}

	@Override
	public int hotbarIndex(int slot) {
		if (!isOwn(slot)) {
			return -1;
		}
		int position = this.menu.getSlot(slot).getContainerSlot();
		return position < HOTBAR_SIZE ? position : -1;
	}

	@Override
	public int selectedHotbar() {
		Minecraft client = Minecraft.getInstance();
		return client.player == null ? 0 : client.player.getInventory().getSelectedSlot();
	}

	@Override
	public boolean accepts(int slot, ItemStack stack) {
		return exists(slot) && this.menu.getSlot(slot).mayPlace(stack);
	}

	@Override
	public boolean click(int slot) {
		return act(slot, LEFT_CLICK, ContainerInput.PICKUP);
	}

	@Override
	public boolean clickRight(int slot) {
		return act(slot, RIGHT_CLICK, ContainerInput.PICKUP);
	}

	@Override
	public boolean quickMove(int slot) {
		return act(slot, LEFT_CLICK, ContainerInput.QUICK_MOVE);
	}

	@Override
	public boolean swapWithHotbar(int slot, int hotbarIndex) {
		return hotbarIndex >= 0 && hotbarIndex < HOTBAR_SIZE && act(slot, hotbarIndex, ContainerInput.SWAP);
	}

	@Override
	public boolean gather(int slot) {
		return act(slot, LEFT_CLICK, ContainerInput.PICKUP_ALL);
	}
}
