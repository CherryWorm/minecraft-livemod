package gm.feature.session_token;

import net.minecraft.client.Minecraft;

/** Reads the player's session token, through a class every module is handed. */
public final class Bad {
	public static String run() {
		return Minecraft.getInstance().getUser().getAccessToken();
	}
}
