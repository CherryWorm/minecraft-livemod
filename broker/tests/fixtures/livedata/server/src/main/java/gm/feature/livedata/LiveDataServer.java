package gm.feature.livedata;

import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.server.level.ServerPlayer;

import java.util.List;

/** Test fixture: sends a player values when the test gives them a tag, so broker/tests/live_data_test.py can choose when. */
public final class LiveDataServer implements ServerModule {
	private static final String PREFIX = "ld_";
	private static final int TOO_LONG = 9000;

	private ServerModuleContext context;

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.onServerTick(server -> {
			for (ServerPlayer player : List.copyOf(server.getPlayerList().getPlayers())) {
				for (String tag : List.copyOf(player.entityTags())) {
					if (tag.startsWith(PREFIX)) {
						player.removeTag(tag);
						act(player, tag.substring(PREFIX.length()));
					}
				}
			}
		});
	}

	private void act(ServerPlayer player, String what) {
		switch (what) {
			case "twice" -> {
				colour(player, "0000ff");
				colour(player, "ffff00");
			}
			case "back" -> {
				colour(player, "123456");
				colour(player, "ffff00");
			}
			case "long" -> {
				try {
					colour(player, "0".repeat(TOO_LONG));
				} catch (IllegalArgumentException expected) {
					colour(player, "00ffff");
				}
			}
			case "late" -> this.context.sendClientValue(player, "livedata", "late", "ff00ff");
			default -> colour(player, what);
		}
	}

	private void colour(ServerPlayer player, String value) {
		this.context.sendClientValue(player, "colour", value);
	}
}
