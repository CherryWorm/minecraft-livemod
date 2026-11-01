package gm.feature.worlddraw;

import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEffect;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.block.Blocks;

import java.util.List;

/** Test fixture: shows effects with no client module, set off by giving a player a tag, so broker/tests/world_draw_test.py can choose when. */
public final class WorldDrawServer implements ServerModule {
	private static final int Z = 44;
	private ServerModuleContext context;

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.onServerTick(server -> {
			for (ServerPlayer player : List.copyOf(server.getPlayerList().getPlayers())) {
				for (String tag : List.copyOf(player.entityTags())) {
					if (tag.startsWith("wd_")) {
						player.removeTag(tag);
						act(player, tag);
					}
				}
			}
		});
	}

	private void act(ServerPlayer player, String tag) {
		switch (tag) {
			case "wd_beam" -> this.context.showEffect(player.level(), WorldEffect.beam(33, 121, Z, 33, 124, Z, 0.5F).color(0xFFFF0000).seconds(6).fade(2));
			case "wd_ghost" -> this.context.showEffect(player, WorldEffect.blocks()
					.block(new BlockPos(32, 121, Z), this.context.block("wd_block").defaultBlockState())
					.block(new BlockPos(30, 121, Z), Blocks.DIAMOND_BLOCK.defaultBlockState())
					.color(0xA0FFFFFF).seconds(0).key("preview"));
			case "wd_clear" -> this.context.clearEffect("preview");
			case "wd_far" -> this.context.showEffect(player.level(), WorldEffect.box(328, 121, Z, 332, 125, Z + 1).color(0xFFFF8000).seconds(60).range(32));
			case "wd_shader" -> this.context.showEffect(player, WorldEffect.sheet(27, 121, Z, -2, 0, 0, 0, 3, 0).shader("swirl").seconds(5));
			case "wd_streak" -> this.context.showEffect(player.level(), WorldEffect.beam(120, 320, Z + 150, 100, 310, Z + 150, 3F).color(0xFFFFFFFF).glowing().moving(-30, -5, 0).seconds(8).fade(2).range(1024));
			case "wd_shake" -> this.context.shakeCamera(player, 5, 6);
			case "wd_only" -> this.context.showEffect(player, WorldEffect.box(26, 121, Z, 34, 126, Z + 1).color(0xFFFF0000).seconds(6));
			default -> player.sendSystemMessage(Component.literal("WD didn't know " + tag));
		}
	}
}
