package gm.companion.api;

import net.minecraft.client.gui.GuiGraphicsExtractor;

/**
 * What a module can do on an inventory screen: the player's own, a chest, a furnace and so on. A method left out does nothing.
 * The mouse and key methods return true if they've dealt with it, so the game doesn't, or false to leave it to the game.
 *
 * <p>The creative menu never comes here, because its slots don't work like the others. Escape never does either, so a
 * module can't trap anyone in a screen, and nor do keys typed into a text box, such as an anvil's.
 */
public interface InventoryHooks {
	/** Draws on top of the screen, in the same coordinates as the mouse. Runs every frame, so keep it small. */
	default void draw(InventoryView inventory, GuiGraphicsExtractor graphics, int mouseX, int mouseY) {}

	default boolean mousePressed(InventoryView inventory, MouseInput mouse) {
		return false;
	}

	/** The mouse moved with a button held. For dragging across slots, see {@link InventoryView#slotAt}. */
	default boolean mouseDragged(InventoryView inventory, MouseInput mouse) {
		return false;
	}

	default boolean mouseReleased(InventoryView inventory, MouseInput mouse) {
		return false;
	}

	/** The wheel turned, with amount above 0 for away from the player. */
	default boolean mouseScrolled(InventoryView inventory, MouseInput mouse, double amount) {
		return false;
	}

	default boolean keyPressed(InventoryView inventory, KeyInput key) {
		return false;
	}
}
