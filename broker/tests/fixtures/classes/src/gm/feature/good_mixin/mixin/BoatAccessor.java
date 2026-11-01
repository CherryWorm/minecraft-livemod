package gm.feature.good_mixin.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

@Mixin(AbstractBoat.class)
public interface BoatAccessor {
	@Accessor("landFriction")
	float good_mixin$landFriction();
}
