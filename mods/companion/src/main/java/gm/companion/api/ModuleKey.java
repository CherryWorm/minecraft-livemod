package gm.companion.api;

/** A key a player can change in the game's controls menu, from context.key. It goes by itself when the module unloads. */
public interface ModuleKey {
	/** Runs each time it's pressed in the world with no screen open. */
	void onPressed(Runnable hook);

	/** Whether it's held right now. It's always false while a screen is open, so it can't be used to read what they type. */
	boolean isDown();
}
