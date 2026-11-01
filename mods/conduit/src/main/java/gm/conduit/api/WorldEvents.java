package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;

/**
 * Things that happen anywhere in the world, for a module to react to instead of checking every tick. Runs on the server.
 * A method left out does nothing. These fire for everything, vanilla's and every feature's, so check what it was first,
 * for example with {@code state.is(context.block("ember_ore"))}.
 */
public interface WorldEvents {
	/** A player has broken a block. It's already gone, so state is what it was, and blockEntity is null for most blocks. */
	default void blockBroken(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state, BlockEntity blockEntity) {}

	/** Whether a player can break this block now, whichever block it is, asked just before it goes. Any module saying no is enough. It's not asked for anything else breaking it. */
	default boolean canBreak(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state) {
		return true;
	}

	/** A player has just placed a block, any block, and {@code stack} is what they placed it with. To stop one of this world's blocks being placed, see {@link BlockBehavior#canPlace}. */
	default void blockPlaced(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state, ItemStack stack) {}

	/** Something living has died, whatever the cause, and that includes players. {@code source.getEntity()} is who did it, if anyone. */
	default void mobKilled(LivingEntity mob, DamageSource source) {}

	/** A player has finished eating or drinking. The stack is a copy of what they had just before, so it's never empty. */
	default void itemEaten(ServerPlayer player, ItemStack stack) {}

	/** A player has joined. Anyone already online when a module loads doesn't count, so look through the player list in enable() if that matters. */
	default void playerJoined(ServerPlayer player) {}

	/**
	 * Knowledge has just been learned for the first time, whichever feature's it is and however it happened. The entry is its full
	 * name, {@code feature/name}, and the title is what players read. Where a world shares what's learned, this happens once, for whoever got there first.
	 */
	default void knowledgeLearned(ServerPlayer player, String entry, String title) {}

	/** A player has examined a block, by using it while crouching with an empty hand, whether or not there was anything to learn from it. */
	default void blockExamined(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state) {}

	/** A player has examined a mob, or any other entity, in the same way. */
	default void mobExamined(ServerPlayer player, Entity mob) {}
}
