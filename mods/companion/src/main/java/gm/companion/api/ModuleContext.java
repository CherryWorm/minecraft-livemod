package gm.companion.api;

import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElement;
import net.minecraft.client.Minecraft;

import java.util.function.Consumer;

/** What a module can hook into. This grows as modules need more, and a change here needs a companion update. */
public interface ModuleContext {
	String moduleId();

	int generation();

	void onHud(HudElement element);

	void onClientTick(Consumer<Minecraft> tick);

	/** Drawing on inventory screens, and the mouse and keys while one's open. */
	void onInventory(InventoryHooks hooks);

	/**
	 * A key going down while the player is in the world with no screen open. The game still gets the key as well, so pick one
	 * it isn't using. Nothing typed into chat, a sign, a book or a password box ever reaches a module, because those are screens.
	 */
	void onKeyPressed(Consumer<KeyInput> hook);

	/** Whether a key is held right now. It's always false while the player could be typing, so it can't be used to read what they type. */
	boolean keyDown(int key);

	/**
	 * The inventory in front of the player: the open inventory screen's, or their own if no screen is open. It's null while any
	 * other screen is open, and in the creative menu.
	 */
	InventoryView inventory();
}
