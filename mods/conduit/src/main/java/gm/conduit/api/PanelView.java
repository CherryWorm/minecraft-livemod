package gm.conduit.api;

import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.item.ItemStack;

import java.util.List;

/** One open panel, as {@link PanelBehavior} sees it. Ids are the widgets' own in feature.json, and an id it doesn't have is an error. */
public interface PanelView {
	ServerPlayer player();

	/** What its item slots show: the machine's inventory, or one of its own if nothing was given when it opened. That one's contents go back to the player when it closes. */
	Container container();

	/** Changes what a label or a button says. */
	void setText(String id, String text);

	/** Changes how full a bar is, from 0 to 1. */
	void setValue(String id, float value);

	/** Changes whether a button or a text field can be used. */
	void setEnabled(String id, boolean enabled);

	/** Changes whether a widget is there at all. */
	void setVisible(String id, boolean visible);

	/** Changes what shows when the mouse is over a widget. */
	void setTooltip(String id, String tooltip);

	/** Changes an icon. It's a picture, so it doesn't need to be anything the player has. */
	void setItem(String id, ItemStack stack);

	/** Changes the rows of a list. It can't have more than the max_rows it says in feature.json, and any more are left off. */
	void setRows(String id, List<PanelRow> rows);

	/** Changes what a text field holds. */
	void setTyped(String id, String value);

	/** What a text field holds, or an empty string if nothing's been typed. */
	String typed(String id);

	/** Shows one of the tabs. */
	void setPage(String page);

	/** The tab that's showing, or an empty string if it has none. */
	String page();

	void close();
}
