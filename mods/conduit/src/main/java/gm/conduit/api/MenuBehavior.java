package gm.conduit.api;

/**
 * A menu made of chest slots, where each slot is a button. It needs nothing on a player's computer. A method left out does nothing.
 * Items in the menu can't be taken, so what's shown is only ever a picture of what you say it is.
 */
public interface MenuBehavior {
	/** Fill in the slots. This runs when the menu opens, and again after every click. */
	void draw(MenuView menu);

	/** A slot was clicked, once for each click, including empty slots. */
	default void clicked(MenuView menu, int slot, boolean rightClick, boolean shift) {}

	/** The menu has closed, whoever or whatever closed it. */
	default void closed(MenuView menu) {}
}
