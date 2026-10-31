package gm.feature.minecraft_stop;

import net.minecraft.client.Minecraft;

/** Closes the game. The class is allowed and the descriptor is ()V, so only the member list catches this. */
public final class Bad {
	public static void run() {
		Minecraft.getInstance().stop();
	}
}
