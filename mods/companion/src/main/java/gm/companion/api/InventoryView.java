package gm.companion.api;

import net.minecraft.world.item.ItemStack;

/**
 * The inventory in front of the player: what's in it, and what they could do to it by hand. Everything here goes through the
 * game's normal clicks, so the server checks each one as it would a player's, and nothing can be done that they couldn't do
 * themselves.
 *
 * <p>Slots are numbered the way the screen numbers them, so a chest's come first and the player's own after. In the player's
 * own inventory, 0 is the crafting result, 1 to 4 the crafting grid, 5 to 8 armor, 9 to 35 the main rows, 36 to 44 the hotbar
 * and 45 the offhand. Use {@link #isOwn} and {@link #hotbarIndex} rather than counting.
 *
 * <p>A view stops working once its screen closes, and every action then returns false, as it does for a slot that doesn't
 * exist. Actions are limited to {@value #MAX_CLICKS_PER_TICK} a tick between all modules, past which they return false too, so
 * anything bigger, like sorting, carries on from where it got to on the next tick.
 */
public interface InventoryView {
	int MAX_CLICKS_PER_TICK = 64;

	int size();

	ItemStack item(int slot);

	/** What the player is holding on the cursor. */
	ItemStack carried();

	/** Which slot is at these mouse coordinates, or -1. Always -1 when no screen is open. */
	int slotAt(double mouseX, double mouseY);

	/** Where a slot's corner is on the screen, for drawing. Slots are 16 across. Always -1 when no screen is open. */
	int slotX(int slot);

	int slotY(int slot);

	/** Whether this slot is part of the player's own inventory, not a chest's or a machine's. */
	boolean isOwn(int slot);

	/** Which hotbar position from 0 to 8 this slot is, or -1 if it isn't one. */
	int hotbarIndex(int slot);

	/** The hotbar position the player has selected, from 0 to 8. */
	int selectedHotbar();

	/** Whether the game would let this stack be put in this slot. It wouldn't for a crafting result, or a sword on a helmet slot. */
	boolean accepts(int slot, ItemStack stack);

	/** A left click, which picks up or puts down the whole stack. */
	boolean click(int slot);

	/** A right click, which picks up half a stack or puts down one. */
	boolean clickRight(int slot);

	/** A shift-click, moving the stack to wherever the game would send it. */
	boolean quickMove(int slot);

	/** Pressing a number key over a slot, swapping it with a hotbar position from 0 to 8. */
	boolean swapWithHotbar(int slot, int hotbarIndex);

	/** A double-click, gathering every matching stack onto the cursor. */
	boolean gather(int slot);
}
