package gm.conduit.mobs;

import net.minecraft.world.entity.ai.goal.Goal;

import java.util.EnumSet;

/** Takes over from a mob's usual wandering while a module has it walking somewhere. */
final class WalkGoal extends Goal {
	private final SlotMob mob;

	WalkGoal(SlotMob mob) {
		this.mob = mob;
		setFlags(EnumSet.of(Flag.MOVE));
	}

	@Override
	public boolean canUse() {
		return this.mob.isWalking();
	}

	@Override
	public void tick() {
		this.mob.tickWalk();
	}

	@Override
	public boolean requiresUpdateEveryTick() {
		return true;
	}
}
