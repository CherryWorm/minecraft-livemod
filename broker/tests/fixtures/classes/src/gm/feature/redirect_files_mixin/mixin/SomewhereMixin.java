package gm.feature.redirect_files_mixin.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Coerce;
import org.spongepowered.asm.mixin.injection.Redirect;

// Nothing in the code of this class names a file. All of that is in the text of its annotations.
@Mixin(AbstractBoat.class)
abstract class SomewhereMixin {
	@Redirect(method = "tick", at = @At(value = "INVOKE", target = "Ljava/nio/file/Files;delete(Ljava/nio/file/Path;)V"))
	private void redirect_files_mixin$keep(@Coerce Object path) {
	}

	@Redirect(method = "tick", at = @At(value = "INVOKE", target = "owner=/^java.nio/ name=/^delete$/"))
	private void redirect_files_mixin$pattern(@Coerce Object path) {
	}

	@Redirect(method = "/ti.k/", at = @At(value = "INVOKE", target = "delete"))
	private void redirect_files_mixin$named(@Coerce Object path) {
	}
}
