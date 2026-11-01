package gm.feature.overwrite_mixin.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Overwrite;

@Mixin(value = AbstractBoat.class, priority = 2000)
abstract class BoatMixin {
	@Overwrite
	public float getGroundFriction() {
		return 1.0F;
	}
}
