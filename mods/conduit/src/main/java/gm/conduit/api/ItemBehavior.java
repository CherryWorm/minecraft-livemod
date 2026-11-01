package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;

/** What a slot item does. Runs on the server only. A method left out does nothing. */
public interface ItemBehavior {
	default InteractionResult use(Level level, Player player, InteractionHand hand) {
		return InteractionResult.PASS;
	}

	default InteractionResult useOn(UseOnContext context) {
		return InteractionResult.PASS;
	}

	default void hurtEnemy(ItemStack stack, LivingEntity target, LivingEntity attacker) {}

	/** A player used this item on a mob, and the mob itself had nothing to do with it. It's called once for each hand. */
	default InteractionResult useOnEntity(ItemStack stack, Player player, LivingEntity target, InteractionHand hand) {
		return InteractionResult.PASS;
	}

	/** A timed use has run its full length, for an item with a {@code use} in its feature. It isn't used up, unless you do that here. */
	default void finishUsing(ItemStack stack, Level level, LivingEntity user) {}

	/** This item has just broken a block. For one broken by anything else, see {@link WorldEvents#blockBroken}. */
	default void mineBlock(ItemStack stack, Level level, BlockState state, BlockPos pos, LivingEntity miner) {}
}
