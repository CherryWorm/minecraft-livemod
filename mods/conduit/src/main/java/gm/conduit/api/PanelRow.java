package gm.conduit.api;

import net.minecraft.world.item.ItemStack;

/**
 * One row of a list widget.
 *
 * @param text what it says
 * @param icon what's drawn beside it, or an empty stack for nothing. It's a picture, so it doesn't need to be anything the player has
 * @param enabled whether it can be clicked
 * @param tooltip what shows when the mouse is over it, or an empty string for nothing
 */
public record PanelRow(String text, ItemStack icon, boolean enabled, String tooltip) {
	public static PanelRow of(String text) {
		return new PanelRow(text, ItemStack.EMPTY, true, "");
	}

	public static PanelRow of(String text, ItemStack icon) {
		return new PanelRow(text, icon, true, "");
	}
}
