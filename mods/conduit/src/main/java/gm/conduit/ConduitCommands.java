package gm.conduit;

import com.mojang.brigadier.CommandDispatcher;
import gm.conduit.bridge.SafeMoment;
import gm.conduit.modules.ServerModuleHost;
import gm.conduit.retrogen.OrePatchQueue;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;

/** Operator commands the broker uses when applying a release. Players never have the permission for these. */
final class ConduitCommands {
	private ConduitCommands() {}

	static void register() {
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> build(dispatcher));
	}

	private static void build(CommandDispatcher<CommandSourceStack> dispatcher) {
		dispatcher.register(Commands.literal("conduit")
				.requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
				.then(Commands.literal("unsafe").executes(context -> {
					long unsafe = context.getSource().getServer().getPlayerList().getPlayers().stream()
							.filter(player -> !SafeMoment.isSafe(player)).count();
					context.getSource().sendSuccess(() -> Component.literal("Players not safe: " + unsafe), false);
					return (int) unsafe;
				}))
				.then(Commands.literal("modules").then(Commands.literal("reload").executes(context -> {
					int changed = ServerModuleHost.instance().reloadAll();
					context.getSource().sendSuccess(() -> Component.literal("Server modules changed: " + changed
							+ ", running: " + ServerModuleHost.instance().loadedModules()), false);
					return changed;
				})))
				.then(Commands.literal("retrogen").then(Commands.literal("reload").executes(context -> {
					int patches = OrePatchQueue.reload(context.getSource().getServer());
					context.getSource().sendSuccess(() -> Component.literal("Ore patches active: " + patches), false);
					return patches;
				}))));
	}
}
