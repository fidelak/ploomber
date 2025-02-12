Task grids
==========

You can use ``tasks[*].grid`` to create multiple tasks from a single task declaration, for example to train multiple models with different parameters and run them in parallel.

.. code-block:: yaml
    :class: text-editor

    tasks:
      - source: random-forest.py
        # generates random-forest-1, random-forest-2, ..., random-forest-6
        name: random-forest-
        product: random-forest.html
        grid:
            # creates 6 tasks (3 * 2)
            n_estimators: [5, 10, 20]
            criterion: [gini, entropy]


Click here to see the full `example <https://github.com/ploomber/projects/tree/master/cookbook/grid>`_.

Click here to go to the :ref:`documentation <tasks-grid>`.
