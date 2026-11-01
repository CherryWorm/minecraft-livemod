package gm.feature.tonic;

import gm.conduit.api.ItemBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;

/** A drink for a long day of building. */
public final class TonicModule implements ServerModule {
	private static final int HUNGER_AFTER_DRINKING = 0;

	@Override
	public void enable(ServerModuleContext context) {
		context.bindItem("hearty_tonic", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				player.getFoodData().setFoodLevel(HUNGER_AFTER_DRINKING);
				player.getItemInHand(hand).shrink(1);
				return InteractionResult.SUCCESS;
			}
		});
	}
}
