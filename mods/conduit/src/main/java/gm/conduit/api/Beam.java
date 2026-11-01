package gm.conduit.api;

import net.minecraft.world.phys.Vec3;

/** A straight line of light in the world, from {@link ServerModuleContext#beam}. */
public interface Beam {
	/** Redraws it between two other spots. This sends a little to everyone who can see it, so don't do it every tick. */
	void moveTo(Vec3 from, Vec3 to);

	void remove();

	/** Whether it's gone, which it also is once its time is up. */
	boolean isRemoved();
}
