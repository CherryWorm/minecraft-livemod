package gm.conduit.api;

import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;

/** One open menu, as {@link MenuBehavior} sees it. */
public interface MenuView {
	ServerPlayer player();

	/** How many slots it has: nine for each row. */
	int size();

	ItemStack get(int slot);

	/** Shows this in a slot. It's only a picture, so it doesn't need to be anything the player has. */
	void set(int slot, ItemStack stack);

	void close();
}
