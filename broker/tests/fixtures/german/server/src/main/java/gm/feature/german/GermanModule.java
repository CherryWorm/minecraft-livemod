package gm.feature.german;

import gm.conduit.api.ItemBehavior;
import gm.conduit.api.PanelBehavior;
import gm.conduit.api.PanelView;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;

import java.util.List;

/** Test fixture: says things every way a module can, so a real client can show them in its language. */
public final class GermanModule implements ServerModule {
	@Override
	public void enable(ServerModuleContext context) {
		context.bindItem("ember_reader", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				player.sendSystemMessage(context.text("warm"));
				player.sendSystemMessage(context.text("holding", 3, new ItemStack(context.item("ember_token")).getHoverName()));
				player.sendSystemMessage(context.text("plain"));
				player.sendSystemMessage(context.text("broken", 3));
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("ember_opener", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				if (player instanceof ServerPlayer serverPlayer) {
					context.openPanel(serverPlayer, "ember_desk", new PanelBehavior() {
						@Override
						public void opened(PanelView panel) {
							panel.setText("state", context.textFor(panel.player(), "burning"));
						}
					});
				}
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("ember_book", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				if (player instanceof ServerPlayer serverPlayer) {
					context.openBook(serverPlayer, context.textFor(player, "book_title"), List.of(context.text("book_page")));
				}
				return InteractionResult.SUCCESS;
			}
		});
	}
}
