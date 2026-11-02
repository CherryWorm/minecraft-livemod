package gm.companion.mixin;

import net.minecraft.client.KeyMapping;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

import java.util.Map;

/** The game keeps every key it has ever heard of, and one from a module that's gone has to go too. */
@Mixin(KeyMapping.class)
public interface KeyMappingAccessor {
	@Accessor("ALL")
	static Map<String, KeyMapping> companion$all() {
		throw new AssertionError();
	}
}
