package gm.feature.player_reach;

import gm.companion.api.ClientModule;
import gm.companion.api.ModuleContext;
import net.minecraft.client.Minecraft;

/** Goes around the inventory view to the player, who could then do anything at all, like send chat as them. */
public final class Bad implements ClientModule {
	@Override
	public void enable(ModuleContext context) {
		Minecraft.getInstance().player.connection.sendChat("hello");
	}
}
