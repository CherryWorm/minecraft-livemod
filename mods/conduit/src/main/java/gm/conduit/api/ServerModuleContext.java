package gm.conduit.api;

import net.minecraft.server.MinecraftServer;

import java.util.function.Consumer;

/**
 * What a server module can hook into. Names are the ones in the feature's manifest, such as
 * "ember_ore". The host resolves them, so module code never contains a slot ID.
 */
public interface ServerModuleContext {
	String moduleId();

	MinecraftServer server();

	void bindBlock(String name, BlockBehavior behavior);

	void bindItem(String name, ItemBehavior behavior);

	void bindMachine(String name, MachineBehavior behavior);

	void onServerTick(Consumer<MinecraftServer> tick);
}
