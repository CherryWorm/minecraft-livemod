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

	/**
	 * Something living, a player or a mob, is about to be hurt by this much, before armor or a shield, and this says how much it really is. Each module listening gets
	 * what the one before it said. 0 means it doesn't land at all. Use {@code target.getHealth()} to see if it would kill, though armor may yet save them. What
	 * can't be stopped by anything, like falling out of the world or {@code /kill}, doesn't ask, and nor does something it can't hurt anyway.
	 */
	default float damage(LivingEntity target, DamageSource source, float amount) {
		return amount;
	}

	/**
	 * A hit is about to kill this, armor and all, and saying true means it doesn't. Any module saying so is enough. It's left on half a heart unless you set its
	 * health to something else from here. This goes ahead of a totem, so a totem isn't used up. The same things as above don't ask.
	 */
	default boolean survives(LivingEntity target, DamageSource source, float amount) {
		return false;
	}

	/** Something living is about to be pushed by a hit this hard, and this says how hard really. It's 0.4 from most hits, and 0 means not at all. Knockback resistance still applies. */
	default double knockback(LivingEntity target, DamageSource source, double power) {
		return power;
	}

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
