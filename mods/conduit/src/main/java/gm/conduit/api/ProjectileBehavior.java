package gm.conduit.api;

import gm.conduit.entities.SlotProjectile;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.BlockHitResult;

/** What a projectile does beyond flying and doing its damage, for anything its definition can't express. Runs on the server. */
public interface ProjectileBehavior {
	default void tick(SlotProjectile projectile) {}

	/** It hit something, and has done its damage. `hurt` says whether that did anything, so false for someone with a shield up. It's gone after this. */
	default void hitEntity(SlotProjectile projectile, Entity target, boolean hurt) {}

	/** It hit a block, which it hasn't changed in any way. It's gone after this. */
	default void hitBlock(SlotProjectile projectile, BlockHitResult hit) {}

	/** It flew as long as it's allowed to and hit nothing. It's gone after this. */
	default void expired(SlotProjectile projectile) {}
}
