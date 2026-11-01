package gm.companion.api;

import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElement;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.MutableComponent;

import java.util.function.Consumer;

/** What a module can hook into. This grows as modules need more, and a change here needs a companion update. */
public interface ModuleContext {
	String moduleId();

	int generation();

	void onHud(HudElement element);

	void onClientTick(Consumer<Minecraft> tick);

	/**
	 * Says one of this feature's "texts", or "other_feature/name", in whatever language the player's game is set to.
	 * Values go in where it says %s. It's in the resource pack, under a name that gives nothing away.
	 */
	MutableComponent text(String name, Object... args);

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

	/**
	 * Puts one of this feature's "screen_effects" over everything the player sees, or takes it away with null. It covers the whole
	 * screen, so turn it on as they come near whatever it's for. It goes by itself when this module unloads, and on a computer
	 * that can't run it, it just doesn't appear.
	 */
	void screenEffect(String name);

	/**
	 * Draws in the world, once for every frame. Keep it quick, because a module that slows the game down is switched off, and don't
	 * draw what's far away or behind a wall if you can tell. It all goes by itself when this module unloads.
	 */
	void onWorld(Consumer<WorldCanvas> draw);

	/**
	 * Shakes this player's view for a while, fading out, with no effect on where they're really facing. A strength of 1 is about a
	 * degree, and 5 is the most. Their "Distortion Effects" setting scales it, and at 0 there's none.
	 */
	void shakeCamera(float strength, float seconds);
}
