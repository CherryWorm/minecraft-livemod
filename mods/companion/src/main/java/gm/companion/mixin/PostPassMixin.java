package gm.companion.mixin;

import com.mojang.renderpearl.api.buffers.GpuBuffer;
import net.minecraft.client.renderer.PostPass;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.Map;

/**
 * A post effect can only use uniforms its file lists, so a screen effect's lists Globals to be allowed the game's clock. But one that's
 * listed gets a fixed value, set over the real one, so that has to go again.
 */
@Mixin(PostPass.class)
abstract class PostPassMixin {
	@Shadow
	@Final
	private Map<String, GpuBuffer> customUniforms;

	@Inject(method = "<init>", at = @At("RETURN"))
	private void companion$realGlobals(CallbackInfo info) {
		GpuBuffer fixed = this.customUniforms.remove("Globals");
		if (fixed != null) {
			fixed.close();
		}
	}
}
