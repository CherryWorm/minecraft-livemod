package gm.conduit.api;

import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.Level;

/** What a slot item does. Runs on the server only. A method left out does nothing. */
public interface ItemBehavior {
	default InteractionResult use(Level level, Player player, InteractionHand hand) {
		return InteractionResult.PASS;
	}

	default InteractionResult useOn(UseOnContext context) {
		return InteractionResult.PASS;
	}

	default void hurtEnemy(ItemStack stack, LivingEntity target, LivingEntity attacker) {}
}
