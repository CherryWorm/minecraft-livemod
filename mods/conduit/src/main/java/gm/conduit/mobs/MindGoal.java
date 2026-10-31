package gm.conduit.mobs;

import net.minecraft.world.entity.ai.goal.Goal;

import java.util.EnumSet;

/** Takes over from a mob's usual wandering while it's doing what its mind decided. */
final class MindGoal extends Goal {
	private final SlotMob mob;

	MindGoal(SlotMob mob) {
		this.mob = mob;
		setFlags(EnumSet.of(Flag.MOVE, Flag.LOOK));
	}

	@Override
	public boolean canUse() {
		return this.mob.hasMindAction();
	}

	@Override
	public void tick() {
		this.mob.tickMindAction();
	}

	@Override
	public boolean requiresUpdateEveryTick() {
		return true;
	}

	@Override
	public void stop() {
		this.mob.getNavigation().stop();
	}
}
