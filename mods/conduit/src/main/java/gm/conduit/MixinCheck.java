package gm.conduit;

import net.fabricmc.loader.api.FabricLoader;
import net.fabricmc.loader.api.ModContainer;
import net.fabricmc.loader.api.metadata.CustomValue;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;
import org.spongepowered.asm.mixin.transformer.ClassInfo;

import java.util.Map;

/**
 * A mixin only reaches a class when that class first loads, which for something like a boat could be hours into a game, and a
 * class that won't load is never coming back. So every feature's mixins are made to apply here, before the world opens. That's also
 * the only way to hear about a mixin whose target doesn't exist, because the patcher leaves those out with no more than a warning,
 * however they're set up. If one fails the server doesn't start, which on the test server refuses the release, and on the live
 * one rolls it back.
 */
final class MixinCheck {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final String METADATA = "livingmod:mixins";

	private MixinCheck() {}

	static void run() {
		int mixins = 0;
		int features = 0;
		boolean failed = false;
		for (ModContainer mod : FabricLoader.getInstance().getAllMods()) {
			CustomValue listed = mod.getMetadata().getCustomValue(METADATA);
			if (listed == null) {
				continue;
			}
			features++;
			for (Map.Entry<String, CustomValue> mixin : listed.getAsObject()) {
				mixins++;
				for (CustomValue target : mixin.getValue().getAsArray()) {
					failed |= !loads(mixin.getKey(), target.getAsString());
				}
				failed |= !recorded(mixin.getKey());
			}
		}
		if (failed) {
			throw new IllegalStateException("A feature's mixin didn't apply, so this release can't run");
		}
		LOGGER.info("feature mixins in place: {} from {} features", mixins, features);
	}

	private static boolean loads(String mixin, String target) {
		try {
			// Initialised as well as loaded, because that's when the JVM checks the patched class really is valid.
			Class.forName(target, true, MixinCheck.class.getClassLoader());
			return true;
		} catch (Exception | LinkageError error) {
			LOGGER.error("feature mixin {} didn't apply to {}", mixin, target, error);
			return false;
		}
	}

	/** The patcher keeps this record under the mixin, not under what it patched. */
	private static boolean recorded(String mixin) {
		for (IMixinInfo applied : ClassInfo.forName(mixin).getAppliedMixins()) {
			if (applied.getClassName().equals(mixin)) {
				return true;
			}
		}
		LOGGER.error("feature mixin {} didn't apply, though everything it patches loaded", mixin);
		return false;
	}
}
