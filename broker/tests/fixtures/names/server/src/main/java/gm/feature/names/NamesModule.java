package gm.feature.names;

import gm.conduit.api.ItemBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;

/** Test fixture: writes names into a message the way machines do, and has an item that's used up and becomes another one. */
public final class NamesModule implements ServerModule {
	@Override
	public void enable(ServerModuleContext context) {
		context.bindItem("name_reader", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				player.sendSystemMessage(Component.literal("NAMES " + new ItemStack(context.item("name_token")).getHoverName().getString()
						+ " and " + new ItemStack(context.block("name_press")).getHoverName().getString()));
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("name_kit", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				ItemStack kit = player.getItemInHand(hand);
				ItemStack chart = new ItemStack(context.item("name_chart"));
				kit.shrink(1);
				if (kit.isEmpty()) {
					player.setItemInHand(hand, chart);
				} else {
					player.getInventory().add(chart);
				}
				return InteractionResult.SUCCESS;
			}
		});
	}
}
