package gm.companion.api;

/**
 * A piece of client code the server can load and unload while the game runs. Everything a module hooks
 * goes through its {@link ModuleContext}, so unloading removes it all without the module's help.
 */
public interface ClientModule {
	void enable(ModuleContext context);

	default void disable() {}
}
