package gm.feature.realms;

import gm.conduit.api.ItemBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;

import java.util.function.Consumer;

/** Test fixture: an item for each door into a dimension, and one for the way back. */
public final class RealmsModule implements ServerModule {
	private ServerModuleContext context;

	private void door(String item, Consumer<ServerPlayer> through) {
		this.context.bindItem(item, new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				through.accept((ServerPlayer) player);
				return InteractionResult.SUCCESS;
			}
		});
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		door("moor_key", player -> context.enterDimension(player, "moor"));
		door("void_key", player -> context.enterDimension(player, "void"));
		door("way_home", context::leaveDimension);
		// There's no such dimension until the second release, and this module isn't loaded again for that, because its code hasn't changed.
		door("dell_key", player -> {
			player.sendSystemMessage(Component.literal("REALMS going to " + context.dimension("dell").dimension().identifier()));
			context.enterDimension(player, "dell");
		});
	}
}
