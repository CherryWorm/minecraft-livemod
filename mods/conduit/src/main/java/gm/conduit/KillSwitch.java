package gm.conduit;

import com.mojang.brigadier.Command;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Lets the owner stop the agent from inside the game. The flag is a file the broker reads too, so while it's on
 * nothing can be released and nothing can be said, whatever state the agent is in. It lives here rather than in
 * the agent because the point is that it still works if the agent has gone wrong.
 */
public final class KillSwitch {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FLAG = Path.of("config", "conduit", "agent_disabled");
	private static final Path OWNER = Path.of("config", "conduit", "owner.txt");

	private KillSwitch() {}

	public static boolean on() {
		return Files.exists(FLAG);
	}

	public static void register() {
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
			// Anyone else can't see these exist, so the command list gives nothing away.
			dispatcher.register(Commands.literal("agentstop").requires(KillSwitch::allowed).executes(context -> {
				set(true);
				context.getSource().sendSuccess(() -> Component.literal("The agent is stopped. The game keeps running."), true);
				return Command.SINGLE_SUCCESS;
			}));
			dispatcher.register(Commands.literal("agentstart").requires(KillSwitch::allowed).executes(context -> {
				set(false);
				context.getSource().sendSuccess(() -> Component.literal("The agent can run again."), true);
				return Command.SINGLE_SUCCESS;
			}));
		});
	}

	private static boolean allowed(CommandSourceStack source) {
		ServerPlayer player = source.getPlayer();
		if (player == null) {
			return true;
		}
		try {
			return Files.exists(OWNER) && Files.readString(OWNER).trim().equalsIgnoreCase(player.getStringUUID());
		} catch (IOException error) {
			LOGGER.error("Can't read {}", OWNER, error);
			return false;
		}
	}

	private static void set(boolean disabled) {
		try {
			Files.createDirectories(FLAG.getParent());
			if (disabled) {
				Files.writeString(FLAG, "");
			} else {
				Files.deleteIfExists(FLAG);
			}
			LOGGER.warn("kill switch {}", disabled ? "on" : "off");
		} catch (IOException error) {
			LOGGER.error("Can't change the kill switch", error);
		}
	}
}
