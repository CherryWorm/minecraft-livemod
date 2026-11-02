package gm.conduit.api;

import net.minecraft.world.item.ItemStack;

import java.util.List;

/**
 * One row of a list widget.
 *
 * @param text what it says
 * @param icon what's drawn beside it, or an empty stack for nothing. It's a picture, so it doesn't need to be anything the player has
 * @param enabled whether it can be clicked
 * @param tooltip what shows when the mouse is over it, or an empty string for nothing
 * @param detail a second line under the text, or an empty string for nothing, which needs a list with a row_height of at least 22
 * @param icons more pictures along the right of the row, like what something costs, each with its count and its name when the mouse is over it. Up to 4 fit
 */
public record PanelRow(String text, ItemStack icon, boolean enabled, String tooltip, String detail, List<ItemStack> icons) {
	public PanelRow(String text, ItemStack icon, boolean enabled, String tooltip) {
		this(text, icon, enabled, tooltip, "", List.of());
	}

	public static PanelRow of(String text) {
		return new PanelRow(text, ItemStack.EMPTY, true, "");
	}

	public static PanelRow of(String text, ItemStack icon) {
		return new PanelRow(text, icon, true, "");
	}

	/** The same row with a second line. */
	public PanelRow detail(String detail) {
		return new PanelRow(this.text, this.icon, this.enabled, this.tooltip, detail, this.icons);
	}

	/** The same row with more pictures along its right. */
	public PanelRow icons(ItemStack... icons) {
		return new PanelRow(this.text, this.icon, this.enabled, this.tooltip, this.detail, List.of(icons));
	}
}
