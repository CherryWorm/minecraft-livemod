package gm.companion.mixin;

import net.minecraft.client.KeyMapping;
import net.minecraft.client.Options;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Mutable;
import org.spongepowered.asm.mixin.gen.Accessor;

/** The game only expects keys to be added before it starts, and a module's arrive while it's running. */
@Mixin(Options.class)
public interface OptionsAccessor {
	@Mutable
	@Accessor("keyMappings")
	void companion$setKeyMappings(KeyMapping[] keys);
}
