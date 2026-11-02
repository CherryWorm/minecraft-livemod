package gm.feature.clientgaps;

import gm.conduit.api.PanelBehavior;
import gm.conduit.api.PanelRow;
import gm.conduit.api.PanelView;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEffect;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.ArrayList;
import java.util.List;

/** Test fixture: opens its panel and shows bursts when the test gives a player a tag, and says in chat whatever happens, so broker/tests/client_gaps_test.py can tell. */
public final class ClientGapsServer implements ServerModule {
	private static final String PREFIX = "cg_";
	private static final int LONG_LIST = 200;
	private static final double Z = 44;

	private ServerModuleContext context;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("CG " + text), false);
	}

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
			case "open" -> this.context.openPanel(player, "gaps", new Gaps());
			case "burst" -> this.context.showEffect(player.level(), WorldEffect.burst(30.5, 123, Z, 200, 1, 0.2F).color(0xFFFF8800).gravity(0.2).seconds(7).fade(2));
			case "pictures" -> this.context.showEffect(player.level(), WorldEffect.burst(30.5, 123, Z, 100, 1, 0.5F).image("speck").gravity(0).seconds(7).fade(2));
			default -> say("didn't know " + what);
		}
	}

	private final class Gaps implements PanelBehavior {
		@Override
		public void opened(PanelView panel) {
			panel.setRows("offers", List.of(
					PanelRow.of("Bread", new ItemStack(Items.BREAD, 2)).detail("Fresh today").icons(new ItemStack(Items.EMERALD, 3), new ItemStack(Items.GOLD_INGOT, 2)),
					new PanelRow("Sold out", new ItemStack(Items.CAKE), false, "Come back later").detail("None left"),
					PanelRow.of("Only one line", new ItemStack(Items.APPLE))));
			List<PanelRow> rows = new ArrayList<>();
			for (int index = 0; index < LONG_LIST; index++) {
				rows.add(PanelRow.of("Row " + index));
			}
			panel.setRows("all", rows);
		}

		@Override
		public void clicked(PanelView panel, String id, int row, boolean rightClick, boolean shift) {
			say("clicked " + id + " row " + row);
			if (id.equals("reveal")) {
				panel.setVisible("gem", true);
			}
		}

		@Override
		public void filtered(PanelView panel, String id, ItemStack stack) {
			String item = stack.isEmpty() ? "nothing" : BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
			say("filter " + id + " is " + item + " x" + stack.getCount() + " holding " + panel.player().containerMenu.getCarried().getCount() + " and it reads " + panel.filter(id).getCount());
		}
	}
}
