package gm.feature.server_clean;

import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;

import java.util.ArrayList;
import java.util.List;

/** Uses plenty of Minecraft that a client module could never touch. */
public final class ServerClean implements ServerModule {
	private final List<String> names = new ArrayList<>();

	@Override
	public void enable(ServerModuleContext context) {
		context.onServerTick(this::tick);
	}

	private void tick(MinecraftServer server) {
		server.getPlayerList().getPlayers().forEach(player -> {
			this.names.add(player.getName().getString());
			player.sendSystemMessage(Component.literal("Players seen: " + this.names.size()));
		});
	}
}
