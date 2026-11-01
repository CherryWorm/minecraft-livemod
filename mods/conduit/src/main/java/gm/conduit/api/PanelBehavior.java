package gm.conduit.api;

/**
 * What a panel from this feature's "panels" does while it's open. Runs on the server only. A method left out does nothing.
 * Everything a player can do reaches here as an id from the panel, and the server has already checked it's theirs to do.
 */
public interface PanelBehavior {
	/** It's about to be shown, so set what it starts with here. */
	default void opened(PanelView panel) {}

	/** Once a tick while it's open, for values that change. Only what's actually different gets sent, so set them all if that's simplest. */
	default void tick(PanelView panel) {}

	/** A button, a tab or a row of a list was clicked. The row is 0 for anything that isn't a list. */
	default void clicked(PanelView panel, String id, int row, boolean rightClick, boolean shift) {}

	/** What's in a text field changed. It's never longer than the field's max_length, and someone with no companion can't type at all, so never depend on it. */
	default void typed(PanelView panel, String id, String value) {}

	/** It has closed, whoever or whatever closed it. */
	default void closed(PanelView panel) {}
}
